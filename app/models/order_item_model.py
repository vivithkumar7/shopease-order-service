
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    func
)

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.order_model import Order


class OrderItem(Base):

    __tablename__ = "order_items"

    __table_args__ = (

        CheckConstraint(
            "quantity > 0",
            name="ck_order_items_quantity"
        ),

        CheckConstraint(
            "unit_price >= 0",
            name="ck_order_items_unit_price"
        ),

        CheckConstraint(
            "discount_amount >= 0",
            name="ck_order_items_discount"
        ),

        CheckConstraint(
            "total_price >= 0",
            name="ck_order_items_total"
        ),

        Index(
            "ix_order_items_order_id",
            "order_id"
        ),

        Index(
            "ix_order_items_product_id",
            "product_id"
        ),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    # Foreign Key to Orders Table
    order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "orders.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )

    # Product Reference from Product Catalog Service
    product_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    # Historical Product Snapshots
    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    # Price at Purchase Time
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    total_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    # Many-to-One Relationship
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="order_items"
    )
