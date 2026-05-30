from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Address, Item, Order, OrderItem


class BusinessRulesTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='buyer',
            email='buyer@example.com',
            password='testpass123'
        )

    def create_order(self, price, quantity=1, city=None):
        item = Item.objects.create(
            title='Test shirt',
            price=price,
            category='S',
            label='P',
            slug='test-shirt',
            description='Test item',
            image='test.jpg',
            stock=10
        )
        order_item = OrderItem.objects.create(
            user=self.user,
            item=item,
            quantity=quantity
        )
        order = Order.objects.create(
            user=self.user,
            ordered_date=timezone.now()
        )
        order.items.add(order_item)

        if city:
            address = Address.objects.create(
                user=self.user,
                street_address='Street 1',
                apartment_address='Apt 1',
                country='CO',
                zip='110111',
                city=city,
                address_type='S'
            )
            order.shipping_address = address
            order.save()

        return order

    def test_city_item_discount_accumulates_with_amount_discount(self):
        order = self.create_order(price=60, quantity=2, city='Bogota')

        self.assertEqual(order.get_subtotal(), 120)
        self.assertEqual(order.get_promotion_discount(), 12)
        self.assertEqual(order.get_city_item_discount(), 2)
        self.assertEqual(order.get_total(), 106)

    def test_city_minimum_purchase_blocks_special_city_when_subtotal_is_low(self):
        order = self.create_order(price=20, quantity=2, city='Medellin')

        self.assertEqual(order.get_city_minimum_purchase(), 50)
        self.assertFalse(order.meets_city_minimum_purchase())

    def test_checkout_rejects_city_with_minimum_purchase_not_met(self):
        order = self.create_order(price=20, quantity=2)
        self.client.login(username='buyer', password='testpass123')

        response = self.client.post(reverse('core:checkout'), {
            'shipping_address': 'Street 1',
            'shipping_address2': 'Apt 1',
            'shipping_country': 'CO',
            'shipping_city': 'Medellin',
            'shipping_zip': '110111',
            'same_billing_address': 'on',
            'payment_option': 'S',
        })

        order.refresh_from_db()
        self.assertRedirects(response, reverse('core:checkout'))
        self.assertIsNotNone(order.shipping_address)
        self.assertIsNone(order.billing_address)
