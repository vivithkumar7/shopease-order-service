
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from app.schemas.order_item_schema import (
    OrderItemCreate,
    OrderItemResponse
)


class ShippingAddressSnapshot(BaseModel):

    recipient_name: str = Field(
        min_length=2,
        max_length=150
    )

    phone_number: str = Field(
        min_length=7,
        max_length=20
    )

    address_line1: str = Field(
        min_length=3,
        max_length=255
    )

    address_line2: str | None = Field(
        default=None,
        max_length=255
    )

    city: str = Field(
        min_length=2,
        max_length=100
    )

    state: str = Field(
        min_length=2,
        max_length=100
    )

    postal_code: str = Field(
        min_length=3,
        max_length=15
    )

    country: str = Field(
        min_length=2,
        max_length=100
    )

    model_config = ConfigDict(
        extra="forbid"
    )


class OrderStatus(str, Enum):

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):

    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class OrderCreate(BaseModel):

    items: list[OrderItemCreate] = Field(
        min_length=1,
        max_length=50,
        description="Order must contain at least one item"
    )

    shipping_address_id: int = Field(
        ...,
        gt=0,
        description="ID of the customer's saved delivery address"
    )

    notes: str | None = Field(
        default=None,
        max_length=2000
    )

    model_config = ConfigDict(
        extra="forbid"
    )


class OrderStatusUpdate(BaseModel):
    order_status: OrderStatus

    model_config = ConfigDict(extra="forbid")


class OrderResponse(BaseModel):

    id: int

    order_number: str

    user_id: int

    shipping_address: ShippingAddressSnapshot

    subtotal: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    discount_amount: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    shipping_charge: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    tax_amount: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    total_amount: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    order_status: OrderStatus

    payment_status: PaymentStatus

    notes: str | None = None

    created_at: datetime

    updated_at: datetime

    items: list[OrderItemResponse] = Field(
        default_factory=list,
        validation_alias="order_items",
    )

    model_config = ConfigDict(
        from_attributes=True
    )


class OrderListResponse(BaseModel):

    total: int

    page: int

    page_size: int

    total_pages: int

    orders: list[OrderResponse]
