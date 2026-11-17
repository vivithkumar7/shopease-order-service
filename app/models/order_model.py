
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Integer,
    String,
    Text,
    JSON,
    Numeric,
    DateTime,
    CheckConstraint,
    UniqueConstraint,
    Index,
    func,
    
)

from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

if TYPE_CHECKING:
    from app.models.order_item_model import OrderItem


class Order(Base):

    __tablename__ = "orders"

    __table_args__ = (

        UniqueConstraint(
            "order_number",
            name="uq_orders_order_number"
        ),

        CheckConstraint(
            "subtotal >= 0",
            name="ck_orders_subtotal"
        ),

        CheckConstraint(
            "discount_amount >= 0",
            name="ck_orders_discount"
        ),

        CheckConstraint(
            "shipping_charge >= 0",
            name="ck_orders_shipping"
        ),

        CheckConstraint(
            "tax_amount >= 0",
            name="ck_orders_tax"
        ),

        CheckConstraint(
            "total_amount >= 0",
            name="ck_orders_total"
        ),

        Index(
            "ix_orders_user_created",
            "user_id",
            "created_at"
        ),

        Index(
            "ix_orders_status_created",
            "order_status",
            "created_at"
        ),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    # Unique Order Number
    order_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False
    )

    # Authenticated User ID
    # No foreign key to another service database
    user_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    # Shipping Address Snapshot
    shipping_address: Mapped[dict] = mapped_column(
        JSON,
        nullable=False
    )

    # Monetary Fields
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    shipping_charge: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    # Order Status
    order_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="PENDING"
    )

    # Payment Status
    payment_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="PENDING"
    )

    # Customer Notes
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )

    # One-to-Many Relationship
    order_items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
