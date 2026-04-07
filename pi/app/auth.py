from fastapi import Header, HTTPException, status

from .config import settings


async def verify_internal_token(x_internal_token: str | None = Header(default=None)) -> str:
    if x_internal_token != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )
    return x_internal_token


async def verify_device_token(authorization: str | None = Header(default=None)) -> str:
    expected = settings.device_shared_token
    if not expected:
        return ""

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )
    return token
