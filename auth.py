import hashlib
import os
from collections.abc import Generator
from datetime import UTC, datetime

from fastapi import Depends, Header
from fastapi.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import create_session_factory
from models import License, Token, User

TOKEN_HASH_SALT = os.getenv("TOKEN_HASH_SALT")
if not TOKEN_HASH_SALT:
    raise RuntimeError("TOKEN_HASH_SALT environment variable is required")

_TOKEN_HASH_SALT: str = TOKEN_HASH_SALT  # type: ignore[assignment]

SessionFactory = create_session_factory()


def get_db() -> Generator[Session, None, None]:
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


def hash_token(raw: str) -> str:
    """Hash a raw token with the salt for storage."""
    return hashlib.sha256((raw + _TOKEN_HASH_SALT).encode()).hexdigest()


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),  # noqa: B008
) -> User:
    """Extract Bearer token, hash, look up, check expiry → 401 on any failure."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    raw_token = authorization.removeprefix("Bearer ")
    token_hash = hash_token(raw_token)

    token_row = db.scalar(
        select(Token).where(Token.token_hash == token_hash)
    )
    if token_row is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    if token_row.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Token expired")

    user = db.scalar(select(User).where(User.id == token_row.user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_active_license(
    user: User = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> User:
    """Require an active Demo license after token authentication."""
    active_license = db.scalars(
        select(License).where(
            License.user_id == user.id,
            License.license_type == "demo",
            License.is_active.is_(True),
        )
    ).first()
    if active_license is None:
        raise HTTPException(status_code=403, detail="No active license")

    return user