from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    role: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid access token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_access_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> str:
    if credentials is None:
        raise _unauthorized()
    return credentials.credentials


def get_current_user(
    access_token: Annotated[str, Depends(get_access_token)],
) -> AuthenticatedUser:
    if not settings.JWT_SECRET_KEY:
        raise _unauthorized()

    try:
        claims = jwt.decode(
            access_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id = int(claims["sub"])
        role = claims["role"]
    except (JWTError, KeyError, TypeError, ValueError):
        raise _unauthorized() from None

    if user_id <= 0 or not isinstance(role, str) or not role.strip():
        raise _unauthorized()
    return AuthenticatedUser(user_id=user_id, role=role.strip().lower())


def require_admin(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    if user.role not in {"admin", "administrator"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role is required",
        )
    return user
