import hashlib
import hmac
import os
import secrets
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import RedirectResponse

from database import create_session_factory
from models import License, Token, User

# ------- Environment --------
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required")

APP_URL = os.getenv("APP_URL")
if not APP_URL:
    raise RuntimeError("APP_URL environment variable is required")

GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
if not GITHUB_OAUTH_CLIENT_ID:
    raise RuntimeError("GITHUB_OAUTH_CLIENT_ID environment variable is required")

GITHUB_OAUTH_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
if not GITHUB_OAUTH_CLIENT_SECRET:
    raise RuntimeError("GITHUB_OAUTH_CLIENT_SECRET environment variable is required")

TOKEN_HASH_SALT = os.getenv("TOKEN_HASH_SALT")
if not TOKEN_HASH_SALT:
    raise RuntimeError("TOKEN_HASH_SALT environment variable is required")

# Help mypy narrow after the RuntimeError gates above
_SECRET_KEY: str = SECRET_KEY  # type: ignore[assignment]
_APP_URL: str = APP_URL  # type: ignore[assignment]
_GITHUB_OAUTH_CLIENT_ID: str = GITHUB_OAUTH_CLIENT_ID  # type: ignore[assignment]
_GITHUB_OAUTH_CLIENT_SECRET: str = GITHUB_OAUTH_CLIENT_SECRET  # type: ignore[assignment]
_TOKEN_HASH_SALT: str = TOKEN_HASH_SALT  # type: ignore[assignment]

# ------- App --------
app = FastAPI()

# Configure allowed hosts from environment variable
# Default includes localhost (dev) and Railway's healthcheck host
# Additional hosts (e.g. custom domains) can be added via ALLOWED_HOSTS env var
allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,healthcheck.railway.app")
allowed_hosts = [host.strip() for host in allowed_hosts_str.split(",")]

app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# ------- DB Session --------
SessionFactory = create_session_factory()


def get_db() -> Generator[Session, None, None]:
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


# ------- Routes --------

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"

OAUTH_SCOPE = "read:user"


def _sign_user_id(user_id: UUID) -> str:
    """HMAC-sign a user_id for token-route auth (scaffold-grade)."""
    signature = hmac.new(
        _SECRET_KEY.encode(), str(user_id).encode(), hashlib.sha256
    ).hexdigest()[:32]
    return signature


def _verify_hmac_user_id(user_id: UUID, sig: str) -> bool:
    """Constant-time HMAC comparison for user_id signatures."""
    expected = _sign_user_id(user_id)
    return hmac.compare_digest(expected, sig)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/login")
def auth_login():
    """Redirect to GitHub OAuth with an HMAC-signed state parameter."""
    nonce = secrets.token_urlsafe(16)
    signature = hmac.new(
        _SECRET_KEY.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()[:32]
    state = f"{nonce}.{signature}"

    params = {
        "client_id": _GITHUB_OAUTH_CLIENT_ID,
        "redirect_uri": f"{_APP_URL}/auth/callback",
        "state": state,
        "scope": OAUTH_SCOPE,
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{qs}")


@app.get("/auth/callback")
def auth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),  # noqa: B008
):
    """Handle OAuth callback: exchange code, upsert user, auto-accept EULA, assign Demo license."""
    # 1. Verify HMAC state
    try:
        nonce, sig = state.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state format")

    expected = hmac.new(
        _SECRET_KEY.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid state signature")

    # 2. Exchange code for access token
    token_response = httpx.post(
        GITHUB_TOKEN_URL,
        data={
            "client_id": _GITHUB_OAUTH_CLIENT_ID,
            "client_secret": _GITHUB_OAUTH_CLIENT_SECRET,
            "code": code,
        },
        headers={"Accept": "application/json"},
    )
    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail="GitHub token exchange failed")
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in GitHub response")

    # 3. Fetch GitHub user identity
    user_response = httpx.get(
        GITHUB_USER_API,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if user_response.status_code != 200:
        raise HTTPException(status_code=400, detail="GitHub user fetch failed")
    github_user = user_response.json()
    github_id = github_user["id"]
    login = github_user["login"]

    # 4. Upsert user (auto-accept EULA on first creation)
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.github_id == github_id))
    if user is None:
        user = User(
            github_id=github_id,
            login=login,
            eula_accepted_at=now,
        )
        db.add(user)
        db.flush()
    else:
        user.login = login

    # 5. Ensure active Demo license
    active_license = db.scalar(
        select(License).where(
            License.user_id == user.id,
            License.license_type == "demo",
            License.is_active == True,
        )
    )
    if active_license is None:
        license_row = License(user_id=user.id, license_type="demo", is_active=True)
        db.add(license_row)

    db.commit()

    return {
        "user_id": str(user.id),
        "login": user.login,
        "eula_accepted": user.eula_accepted_at is not None,
        "license": "demo",
    }


TOKEN_TTL_DAYS = 90


def _hash_token(raw: str) -> str:
    """Hash a raw token with the salt for storage."""
    return hashlib.sha256((raw + _TOKEN_HASH_SALT).encode()).hexdigest()


@app.get("/auth/token")
def auth_token(
    user_id: str = Query(...),
    sig: str = Query(...),
    db: Session = Depends(get_db),  # noqa: B008
):
    """Generate an API token for a user, gated on HMAC-signed user_id, EULA, and license."""
    # 1. Verify HMAC signature
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    if not _verify_hmac_user_id(uid, sig):
        raise HTTPException(status_code=400, detail="Invalid user_id signature")

    # 2. Find user
    user = db.scalar(select(User).where(User.id == uid))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # 3. EULA gate
    if user.eula_accepted_at is None:
        raise HTTPException(status_code=400, detail="EULA must be accepted before generating a token")

    # 4. Active license gate
    active_license = db.scalar(
        select(License).where(
            License.user_id == user.id,
            License.is_active == True,
        )
    )
    if active_license is None:
        raise HTTPException(status_code=403, detail="No active license")

    # 5. Generate token (hash-only storage)
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=TOKEN_TTL_DAYS)

    token_row = Token(
        user_id=user.id,
        token_hash=token_hash,
        name="default",
        expires_at=expires_at,
    )
    db.add(token_row)
    db.commit()

    return {
        "token": raw,
        "expires_at": expires_at.isoformat(),
        "name": "default",
    }


@app.post("/auth/token/expire")
def auth_token_expire(
    user_id: str = Query(...),
    sig: str = Query(...),
    body: dict = Body(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """Expire a token by setting its expires_at to now."""
    # 1. Verify HMAC signature
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    if not _verify_hmac_user_id(uid, sig):
        raise HTTPException(status_code=400, detail="Invalid user_id signature")

    # 2. Compute token_hash
    raw_token = body.get("token")
    token_hash = body.get("token_hash")
    if not token_hash and not raw_token:
        raise HTTPException(status_code=400, detail="Provide 'token' or 'token_hash'")
    if raw_token:
        token_hash = _hash_token(raw_token)

    # 3. Find token belonging to user
    token_row = db.scalar(
        select(Token).where(
            Token.token_hash == token_hash,
            Token.user_id == uid,
        )
    )
    if token_row is None:
        raise HTTPException(status_code=404, detail="Token not found or does not belong to this user")

    # 4. Expire
    token_row.expires_at = datetime.now(UTC)
    db.commit()

    return {"expired": True}
