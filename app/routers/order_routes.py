from datetime import datetime
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import (
    AuthenticatedUser,
    get_access_token,
    get_current_user,
    require_admin,
)
from app.database.connection import get_db
from app.schemas.order_schema import (
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatus,
    OrderStatusUpdate,
)
from app.services import order_service


router = APIRouter(prefix="/api/orders", tags=["orders"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
Administrator = Annotated[AuthenticatedUser, Depends(require_admin)]
AccessToken = Annotated[str, Depends(get_access_token)]


@router.post(
    "/",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    request: OrderCreate,
    db: DatabaseSession,
    user: CurrentUser,
    access_token: AccessToken,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=255),
    ],
) -> OrderResponse:
    return order_service.create_order(
        db,
        user,
        request,
        access_token,
        idempotency_key,
    )


@router.get("/", response_model=OrderListResponse)
def list_orders(
    db: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    order_status: OrderStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> OrderListResponse:
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="created_from must be earlier than or equal to created_to",
        )
    total, orders = order_service.list_orders(
        db,
        user,
        page=page,
        page_size=page_size,
        order_status=order_status,
        created_from=created_from,
        created_to=created_to,
    )
    return OrderListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size),
        orders=orders,
    )


@router.get("/number/{order_number}", response_model=OrderResponse)
def get_order_by_number(
    order_number: str,
    db: DatabaseSession,
    user: CurrentUser,
) -> OrderResponse:
    return order_service.get_order_by_number(db, order_number, user)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: DatabaseSession,
    user: CurrentUser,
) -> OrderResponse:
    return order_service.get_order_by_id(db, order_id, user)


@router.patch("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    update: OrderStatusUpdate,
    db: DatabaseSession,
    _: Administrator,
) -> OrderResponse:
    return order_service.update_order_status(db, order_id, update)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    db: DatabaseSession,
    user: CurrentUser,
    access_token: AccessToken,
) -> OrderResponse:
    return order_service.cancel_order(db, order_id, user, access_token)
