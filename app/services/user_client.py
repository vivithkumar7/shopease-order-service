from typing import Any

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.order_schema import ShippingAddressSnapshot


def _address_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="User Service returned an invalid address response",
        )
    data = payload.get("data", payload)
    if isinstance(data, dict):
        data = data.get("address", data)
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="User Service returned an invalid address response",
        )
    return data


def get_user_profile(user_id: int, access_token: str) -> dict[str, Any]:
    if not settings.USER_SERVICE_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User Service is not configured",
        )

    path = settings.USER_PROFILE_PATH_TEMPLATE.format(user_id=user_id)
    try:
        response = httpx.get(
            f"{settings.USER_SERVICE_URL.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=settings.SERVICE_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User Service is unavailable",
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user profile was not found",
        )
    if response.is_error:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if response.status_code >= 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=code,
            detail="User Service could not validate the authenticated user",
        )

    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Invalid profile response")
        profile = payload.get("data", payload)
        if isinstance(profile, dict):
            profile = profile.get("profile", profile)
        if (
            not isinstance(profile, dict)
            or isinstance(profile.get("id"), bool)
            or int(profile["id"]) != user_id
        ):
            raise ValueError("Profile ID mismatch")
        if profile.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated user account is inactive",
            )
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="User Service returned an invalid user profile",
        ) from exc
    return profile


def get_shipping_address(
    user_id: int,
    address_id: int,
    access_token: str,
) -> dict[str, Any]:
    if not settings.USER_SERVICE_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User Service is not configured",
        )

    path = settings.USER_ADDRESS_PATH_TEMPLATE.format(
        user_id=user_id,
        address_id=address_id,
    )
    try:
        response = httpx.get(
            f"{settings.USER_SERVICE_URL.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=settings.SERVICE_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User Service is unavailable",
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Shipping address was not found for this user",
        )
    if response.is_error:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if response.status_code >= 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=code,
            detail="User Service could not validate the shipping address",
        )

    try:
        address = _address_payload(response.json())
        if "id" in address and (
            isinstance(address["id"], bool) or int(address["id"]) != address_id
        ):
            raise ValueError("Address ID mismatch")
        if "user_id" in address and (
            isinstance(address["user_id"], bool) or int(address["user_id"]) != user_id
        ):
            raise ValueError("Address owner mismatch")
        snapshot_fields = ShippingAddressSnapshot.model_fields
        snapshot = ShippingAddressSnapshot.model_validate(
            {key: value for key, value in address.items() if key in snapshot_fields}
        )
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="User Service returned an invalid or mismatched address",
        ) from exc

    return snapshot.model_dump(mode="json")
