
from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field
)


class OrderItemCreate(BaseModel):

    product_id: int = Field(
        ...,
        gt=0,
        description="Product ID must be greater than zero"
    )

    quantity: int = Field(
        ...,
        gt=0,
        le=1000,
        description="Quantity must be between 1 and 1000"
    )

    model_config = ConfigDict(
        extra="forbid"
    )


class OrderItemResponse(BaseModel):

    id: int

    order_id: int

    product_id: int

    product_name: str

    sku: str

    unit_price: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    quantity: int

    discount_amount: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    total_price: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )
