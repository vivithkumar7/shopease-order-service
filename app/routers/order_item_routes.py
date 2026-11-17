from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, get_current_user
from app.database.connection import get_db
from app.schemas.order_item_schema import OrderItemResponse
from app.services.order_service import get_order_by_id


router = APIRouter(prefix="/api/orders", tags=["order items"])


@router.get(
    "/{order_id}/items",
    response_model=list[OrderItemResponse],
)
def get_order_items(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[OrderItemResponse]:
    order = get_order_by_id(db, order_id, user)
    return order.order_items
