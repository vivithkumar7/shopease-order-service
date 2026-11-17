from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


@dataclass(frozen=True)
class ProductSnapshot:
    product_id: int
    name: str
    sku: str
    unit_price: Decimal
    available_stock: int


def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Product Catalog Service returned an invalid response",
        )
    product = payload.get("data", payload)
    if isinstance(product, dict):
        product = product.get("product", product)
    if not isinstance(product, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Product Catalog Service returned an invalid response",
        )
    return product


def get_product(product_id: int, access_token: str) -> ProductSnapshot:
    if not settings.PRODUCT_SERVICE_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product Catalog Service is not configured",
        )

    path = settings.PRODUCT_PATH_TEMPLATE.format(product_id=product_id)
    try:
        response = httpx.get(
            f"{settings.PRODUCT_SERVICE_URL.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=settings.SERVICE_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product Catalog Service is unavailable",
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Product {product_id} was not found",
        )
    if response.is_error:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if response.status_code >= 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=code,
            detail="Product Catalog Service could not validate the product",
        )

    try:
        product = _unwrap(response.json())
        raw_id = product["id"]
        if isinstance(raw_id, bool):
            raise ValueError("Product ID must be an integer")
        returned_id = int(raw_id)
        name = str(product["name"]).strip()
        sku = str(product["sku"]).strip()
        unit_price = Decimal(str(product["price"])).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        stock_value = product.get("available_stock", product.get("stock"))
        stock_decimal = Decimal(str(stock_value))
        if (
            not stock_decimal.is_finite()
            or stock_decimal != stock_decimal.to_integral_value()
        ):
            raise ValueError("Stock must be a whole number")
        available_stock = int(stock_decimal)
        active = product.get("is_active", product.get("active"))
    except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Product Catalog Service returned incomplete product details",
        ) from exc

    if (
        returned_id != product_id
        or not name
        or not sku
        or not unit_price.is_finite()
        or unit_price < 0
        or unit_price > Decimal("9999999999.99")
        or available_stock < 0
        or not isinstance(active, bool)
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Product Catalog Service returned invalid product details",
        )
    if not active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product {product_id} is inactive",
        )
    return ProductSnapshot(
        product_id=product_id,
        name=name,
        sku=sku,
        unit_price=unit_price,
        available_stock=available_stock,
    )


def reserve_inventory(
    operation_id: str,
    items: list[dict[str, int]],
    access_token: str,
) -> None:
    _inventory_request(
        method="post",
        path=settings.INVENTORY_RESERVATIONS_PATH,
        operation_id=operation_id,
        items=items,
        access_token=access_token,
    )


def release_inventory(
    reservation_id: str,
    operation_id: str,
    access_token: str,
) -> None:
    path = (
        f"{settings.INVENTORY_RESERVATIONS_PATH.rstrip('/')}/"
        f"{reservation_id}/release"
    )
    _inventory_request(
        method="post",
        path=path,
        operation_id=operation_id,
        items=None,
        access_token=access_token,
    )


def _inventory_request(
    *,
    method: str,
    path: str,
    operation_id: str,
    items: list[dict[str, int]] | None,
    access_token: str,
) -> None:
    if not settings.PRODUCT_SERVICE_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product Catalog Service is not configured",
        )

    body: dict[str, Any] = {"operation_id": operation_id}
    if items is not None:
        body["items"] = items
    try:
        response = httpx.request(
            method,
            f"{settings.PRODUCT_SERVICE_URL.rstrip('/')}/{path.lstrip('/')}",
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Idempotency-Key": operation_id,
            },
            timeout=settings.SERVICE_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product Catalog inventory service is unavailable",
        ) from exc

    if response.status_code == status.HTTP_409_CONFLICT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Insufficient inventory for one or more products"
                if items is not None
                else "Product Catalog Service rejected the inventory release"
            ),
        )
    if response.is_error:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if response.status_code >= 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=code,
            detail="Product Catalog Service could not complete the inventory operation",
        )
