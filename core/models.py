from django.db.models.signals import post_save
from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.shortcuts import reverse
from django_countries.fields import CountryField


CATEGORY_CHOICES = (
    ('S', 'Shirt'),
    ('SW', 'Sport wear'),
    ('OW', 'Outwear')
)

LABEL_CHOICES = (
    ('P', 'primary'),
    ('S', 'secondary'),
    ('D', 'danger')
)

ADDRESS_CHOICES = (
    ('B', 'Billing'),
    ('S', 'Shipping'),
)

# ============================================================
# FUNCIONALIDAD 3: Ciudades con despacho disponible
# ============================================================
ALLOWED_CITIES = [
    'bogota', 'medellin', 'cali', 'barranquilla', 'cartagena',
    'bucaramanga', 'pereira', 'manizales', 'pasto', 'cucuta'
]

# ============================================================
# FUNCIONALIDAD 2: Monto mínimo para promoción automática
# ============================================================
PROMOTION_THRESHOLD = 100   # USD — si el carrito supera este valor
PROMOTION_DISCOUNT = 0.10   # 10% de descuento automático

# ============================================================
# REGLAS DE NEGOCIO COMPUESTAS
# ============================================================
MINIMUM_PURCHASE_BY_CITY = {
    'bogota': 50,
    'medellin': 50,
    'cali': 40,
}

CITY_ITEM_DISCOUNT_CITIES = ['bogota', 'medellin']
CITY_ITEM_DISCOUNT_AMOUNT = 1


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stripe_customer_id = models.CharField(max_length=50, blank=True, null=True)
    one_click_purchasing = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username


class Item(models.Model):
    title = models.CharField(max_length=100)
    price = models.FloatField()
    discount_price = models.FloatField(blank=True, null=True)
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=2)
    label = models.CharField(choices=LABEL_CHOICES, max_length=1)
    slug = models.SlugField()
    description = models.TextField()
    image = models.ImageField()
    # ============================================================
    # FUNCIONALIDAD 1: Control de inventario
    # ============================================================
    stock = models.IntegerField(default=0)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("core:product", kwargs={
            'slug': self.slug
        })

    def get_add_to_cart_url(self):
        return reverse("core:add-to-cart", kwargs={
            'slug': self.slug
        })

    def get_remove_from_cart_url(self):
        return reverse("core:remove-from-cart", kwargs={
            'slug': self.slug
        })

    def is_in_stock(self):
        """Retorna True si hay al menos 1 unidad disponible."""
        return self.stock > 0

    def has_enough_stock(self, quantity):
        """Retorna True si hay suficiente stock para la cantidad solicitada."""
        return self.stock >= quantity


class OrderItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    ordered = models.BooleanField(default=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} of {self.item.title}"

    def get_total_item_price(self):
        return self.quantity * self.item.price

    def get_total_discount_item_price(self):
        return self.quantity * self.item.discount_price

    def get_amount_saved(self):
        return self.get_total_item_price() - self.get_total_discount_item_price()

    def get_final_price(self):
        if self.item.discount_price:
            return self.get_total_discount_item_price()
        return self.get_total_item_price()


class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    ref_code = models.CharField(max_length=20, blank=True, null=True)
    items = models.ManyToManyField(OrderItem)
    start_date = models.DateTimeField(auto_now_add=True)
    ordered_date = models.DateTimeField()
    ordered = models.BooleanField(default=False)
    shipping_address = models.ForeignKey(
        'Address', related_name='shipping_address', on_delete=models.SET_NULL, blank=True, null=True)
    billing_address = models.ForeignKey(
        'Address', related_name='billing_address', on_delete=models.SET_NULL, blank=True, null=True)
    payment = models.ForeignKey(
        'Payment', on_delete=models.SET_NULL, blank=True, null=True)
    coupon = models.ForeignKey(
        'Coupon', on_delete=models.SET_NULL, blank=True, null=True)
    being_delivered = models.BooleanField(default=False)
    received = models.BooleanField(default=False)
    refund_requested = models.BooleanField(default=False)
    refund_granted = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username

    def get_subtotal(self):
        """Subtotal antes de cupón y promoción automática."""
        total = 0
        for order_item in self.items.all():
            total += order_item.get_final_price()
        return total

    def get_promotion_discount(self):
        """
        FUNCIONALIDAD 2: Promoción automática por monto.
        Si el subtotal supera PROMOTION_THRESHOLD, aplica PROMOTION_DISCOUNT.
        """
        subtotal = self.get_subtotal()
        if subtotal > PROMOTION_THRESHOLD:
            return round(subtotal * PROMOTION_DISCOUNT, 2)
        return 0

    def has_promotion(self):
        """Retorna True si aplica la promoción automática."""
        return self.get_subtotal() > PROMOTION_THRESHOLD

    def get_shipping_city(self):
        """Retorna la ciudad de envio normalizada para reglas de negocio."""
        if not self.shipping_address or not self.shipping_address.city:
            return ''
        return self.shipping_address.city.strip().lower()

    def get_total_quantity(self):
        """Total de unidades del carrito."""
        total = 0
        for order_item in self.items.all():
            total += order_item.quantity
        return total

    def get_city_item_discount(self):
        """
        Descuento acumulable por ciudad.
        Bogota y Medellin reciben USD 1 de descuento por cada articulo.
        """
        if self.get_shipping_city() in CITY_ITEM_DISCOUNT_CITIES:
            return round(self.get_total_quantity() * CITY_ITEM_DISCOUNT_AMOUNT, 2)
        return 0

    def get_city_minimum_purchase(self):
        """Monto minimo de compra requerido para ciudades especiales."""
        return MINIMUM_PURCHASE_BY_CITY.get(self.get_shipping_city())

    def meets_city_minimum_purchase(self):
        """Valida el subtotal minimo cuando la ciudad tiene regla especial."""
        minimum_purchase = self.get_city_minimum_purchase()
        if minimum_purchase is None:
            return True
        return self.get_subtotal() >= minimum_purchase

    def get_total(self):
        """Total final: subtotal - cupon - promocion automatica - descuento por ciudad."""
        total = self.get_subtotal()
        if self.coupon:
            total -= self.coupon.amount
        total -= self.get_promotion_discount()
        total -= self.get_city_item_discount()
        return max(total, 0)  # El total nunca puede ser negativo


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    street_address = models.CharField(max_length=100)
    apartment_address = models.CharField(max_length=100)
    country = CountryField(multiple=False)
    zip = models.CharField(max_length=100)
    # ============================================================
    # FUNCIONALIDAD 3: Ciudad para validar despacho
    # ============================================================
    city = models.CharField(max_length=100, blank=True, null=True)
    address_type = models.CharField(max_length=1, choices=ADDRESS_CHOICES)
    default = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username

    def is_city_allowed(self):
        """
        FUNCIONALIDAD 3: Verifica si la ciudad tiene despacho disponible.
        Retorna True si la ciudad está en la lista de ciudades permitidas.
        """
        if not self.city:
            return False
        return self.city.strip().lower() in ALLOWED_CITIES

    class Meta:
        verbose_name_plural = 'Addresses'


class Payment(models.Model):
    stripe_charge_id = models.CharField(max_length=50)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.SET_NULL, blank=True, null=True)
    amount = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


class Coupon(models.Model):
    code = models.CharField(max_length=15)
    amount = models.FloatField()

    def __str__(self):
        return self.code


class Refund(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    reason = models.TextField()
    accepted = models.BooleanField(default=False)
    email = models.EmailField()

    def __str__(self):
        return f"{self.pk}"


def userprofile_receiver(sender, instance, created, *args, **kwargs):
    if created:
        userprofile = UserProfile.objects.create(user=instance)


post_save.connect(userprofile_receiver, sender=settings.AUTH_USER_MODEL)
