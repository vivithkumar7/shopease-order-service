import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import AuthenticatedUser
from app.models import InventoryOperation, Order, OrderItem
from app.schemas.order_schema import (
    OrderCreate,
    OrderStatus,
    OrderStatusUpdate,
)
from app.services import product_client, user_client

CENT = Decimal("0.01")
ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"PROCESSING", "CANCELLED"},
    "PROCESSING": {"SHIPPED"},
    "SHIPPED": {"DELIVERED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order database operation failed",
        ) from exc


def _find_order_operation(
    db: Session,
    *,
    order_id: int,
    operation_type: str,
) -> InventoryOperation | None:
    return db.scalar(
        select(InventoryOperation).where(
            InventoryOperation.order_id == order_id,
            InventoryOperation.operation_type == operation_type,
        )
    )


def _active_orders_query(db: Session):
    reservation_complete = exists(
        select(InventoryOperation.id).where(
            InventoryOperation.order_id == Order.id,
            InventoryOperation.operation_type == "RESERVE",
            InventoryOperation.state == "COMPLETE",
        )
    )
    reservation_exists = exists(
        select(InventoryOperation.id).where(
            InventoryOperation.order_id == Order.id,
            InventoryOperation.operation_type == "RESERVE",
        )
    )
    return db.query(Order).filter(or_(~reservation_exists, reservation_complete))


def _get_order(
    db: Session,
    order_id: int,
    user: AuthenticatedUser,
    *,
    for_update: bool = False,
) -> Order:
    query = (
        _active_orders_query(db)
        .options(selectinload(Order.order_items))
        .filter(Order.id == order_id)
    )
    if for_update:
        query = query.with_for_update()
    order = query.first()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if user.role not in {"admin", "administrator"} and order.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this order",
        )
    return order


def _resume_reservation(
    db: Session,
    operation: InventoryOperation,
    access_token: str,
) -> Order:
    if operation.state == "COMPLETE":
        if operation.order_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The idempotent order operation has no order",
            )
        return (
            db.query(Order)
            .options(selectinload(Order.order_items))
            .filter(Order.id == operation.order_id)
            .one()
        )
    if operation.state == "FAILED" or operation.order_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This idempotency key belongs to a failed order request",
        )

    try:
        product_client.reserve_inventory(
            operation.operation_id,
            operation.payload["items"],
            access_token,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            order = db.get(Order, operation.order_id)
            operation.order_id = None
            operation.state = "FAILED"
            operation.error_detail = str(exc.detail)
            if order is not None:
                db.delete(order)
            _commit(db)
        raise
    operation.state = "COMPLETE"
    operation.error_detail = None
    _commit(db)
    return (
        db.query(Order)
        .options(selectinload(Order.order_items))
        .filter(Order.id == operation.order_id)
        .one()
    )


def create_order(
    db: Session,
    user: AuthenticatedUser,
    request: OrderCreate,
    access_token: str,
    idempotency_key: str,
) -> Order:
    request_payload = request.model_dump(mode="json")
    request_hash = _request_hash(request_payload)
    prior = db.scalar(
        select(InventoryOperation).where(
            InventoryOperation.user_id == user.user_id,
            InventoryOperation.idempotency_key == idempotency_key,
        )
    )
    if prior is not None:
        if prior.request_hash != request_hash or prior.operation_type != "RESERVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency-Key was already used for a different request",
            )
        return _resume_reservation(db, prior, access_token)

    user_client.get_user_profile(user.user_id, access_token)
    shipping_address = user_client.get_shipping_address(
        user.user_id,
        request.shipping_address_id,
        access_token,
    )

    quantities: dict[int, int] = {}
    for item in request.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        if quantities[item.product_id] > 1000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Combined quantity for product {item.product_id} exceeds 1000",
            )

    products = {
        product_id: product_client.get_product(product_id, access_token)
        for product_id in quantities
    }
    for product_id, quantity in quantities.items():
        if quantity > products[product_id].available_stock:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Insufficient stock for product {product_id}",
            )

    unit_prices = {
        product_id: _money(product.unit_price)
        for product_id, product in products.items()
    }
    line_totals = {
        product_id: _money(unit_prices[product_id] * quantities[product_id])
        for product_id in products
    }
    subtotal = _money(sum(line_totals.values(), Decimal("0.00")))
    if subtotal > Decimal("9999999999.99"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Order subtotal exceeds the supported monetary range",
        )
    discount_amount = Decimal("0.00")
    tax_rate = settings.TAX_RATE
    shipping_charge = _money(settings.SHIPPING_CHARGE)
    tax_amount = _money((subtotal - discount_amount) * tax_rate)
    total_amount = _money(subtotal - discount_amount + tax_amount + shipping_charge)
    if tax_amount > Decimal("9999999999.99") or total_amount > Decimal("9999999999.99"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Calculated order totals exceed the supported monetary range",
        )

    order = Order(
        order_number=f"ORD-{uuid.uuid4().hex.upper()}",
        user_id=user.user_id,
        shipping_address=shipping_address,
        subtotal=subtotal,
        discount_amount=discount_amount,
        shipping_charge=shipping_charge,
        tax_amount=tax_amount,
        total_amount=total_amount,
        order_status=OrderStatus.PENDING.value,
        payment_status="PENDING",
        notes=request.notes,
    )
    for product_id, quantity in quantities.items():
        product = products[product_id]
        order.order_items.append(
            OrderItem(
                product_id=product.product_id,
                product_name=product.name,
                sku=product.sku,
                unit_price=unit_prices[product_id],
                quantity=quantity,
                discount_amount=Decimal("0.00"),
                total_price=line_totals[product_id],
            )
        )
    db.add(order)
    try:
        db.flush()
        operation = InventoryOperation(
            operation_id=str(uuid.uuid4()),
            order_id=order.id,
            user_id=user.user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation_type="RESERVE",
            state="PENDING",
            payload={
                "items": [
                    {"product_id": product_id, "quantity": quantity}
                    for product_id, quantity in quantities.items()
                ]
            },
        )
        db.add(operation)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        prior = db.scalar(
            select(InventoryOperation).where(
                InventoryOperation.user_id == user.user_id,
                InventoryOperation.idempotency_key == idempotency_key,
            )
        )
        if prior is not None:
            if prior.request_hash != request_hash or prior.operation_type != "RESERVE":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key was already used for a different request",
                ) from exc
            return _resume_reservation(db, prior, access_token)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save the order",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save the order",
        ) from exc

    return _resume_reservation(db, operation, access_token)


def list_orders(
    db: Session,
    user: AuthenticatedUser,
    *,
    page: int,
    page_size: int,
    order_status: OrderStatus | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> tuple[int, list[Order]]:
    query = _active_orders_query(db).options(selectinload(Order.order_items))
    if user.role not in {"admin", "administrator"}:
        query = query.filter(Order.user_id == user.user_id)
    if order_status is not None:
        query = query.filter(Order.order_status == order_status.value)
    if created_from is not None:
        query = query.filter(Order.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Order.created_at <= created_to)
    total = query.order_by(None).count()
    orders = (
        query.order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, orders


def get_order_by_id(
    db: Session,
    order_id: int,
    user: AuthenticatedUser,
) -> Order:
    return _get_order(db, order_id, user)


def get_order_by_number(
    db: Session,
    order_number: str,
    user: AuthenticatedUser,
) -> Order:
    order = (
        _active_orders_query(db)
        .options(selectinload(Order.order_items))
        .filter(Order.order_number == order_number)
        .first()
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if user.role not in {"admin", "administrator"} and order.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this order",
        )
    return order


def update_order_status(
    db: Session,
    order_id: int,
    update: OrderStatusUpdate,
) -> Order:
    order = _get_order(
        db,
        order_id,
        AuthenticatedUser(user_id=0, role="admin"),
        for_update=True,
    )
    release_operation = _find_order_operation(
        db,
        order_id=order.id,
        operation_type="RELEASE",
    )
    if release_operation is not None and release_operation.state == "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order cancellation is in progress",
        )
    destination = update.order_status.value
    if destination == OrderStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use the cancellation endpoint so reserved inventory is released",
        )
    if destination not in ORDER_STATUS_TRANSITIONS[order.order_status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Order status cannot transition from {order.order_status} "
                f"to {destination}"
            ),
        )
    order.order_status = destination
    _commit(db)
    db.refresh(order)
    return order


def cancel_order(
    db: Session,
    order_id: int,
    user: AuthenticatedUser,
    access_token: str,
) -> Order:
    order = _get_order(db, order_id, user, for_update=True)
    if order.order_status == OrderStatus.CANCELLED.value:
        return order
    if order.order_status not in {"PENDING", "CONFIRMED"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Orders in {order.order_status} status cannot be cancelled",
        )

    operation = _find_order_operation(
        db,
        order_id=order.id,
        operation_type="RELEASE",
    )
    if operation is None:
        reservation = _find_order_operation(
            db,
            order_id=order.id,
            operation_type="RESERVE",
        )
        if reservation is None or reservation.state != "COMPLETE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order inventory is not in a cancellable state",
            )
        operation = InventoryOperation(
            operation_id=str(uuid.uuid4()),
            order_id=order.id,
            user_id=order.user_id,
            idempotency_key=f"cancel-{uuid.uuid4()}",
            request_hash=_request_hash({"order_id": order.id, "action": "cancel"}),
            operation_type="RELEASE",
            state="PENDING",
            payload={"reservation_id": reservation.operation_id},
        )
        db.add(operation)
        _commit(db)
    elif operation.state == "COMPLETE":
        if order.order_status != OrderStatus.CANCELLED.value:
            order.order_status = OrderStatus.CANCELLED.value
            _commit(db)
        return order

    product_client.release_inventory(
        operation.payload["reservation_id"],
        operation.operation_id,
        access_token,
    )
    operation.state = "COMPLETE"
    operation.error_detail = None
    order.order_status = OrderStatus.CANCELLED.value
    _commit(db)
    db.refresh(order)
    return order
