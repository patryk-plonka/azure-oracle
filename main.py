import json
import logging
import os
import secrets
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from auth import hash_token, require_active_license
from database import create_session_factory
from logging_middleware import (
    RequestLoggingMiddleware,
    SuppressUvicornAccessLogFilter,
    SuppressUvicornTracebackFilter,
    log_request,
    log_unhandled_exception,
)
from models import (
    AuthGrant,
    License,
    LifecycleEvent,
    Limitation,
    OAuthState,
    Token,
    User,
)
from query import aggregate_verdict, map_support_status, resolve_query
from schemas import (
    EulaAcceptanceRequest,
    EulaAcceptanceResponse,
    EulaDocumentResponse,
    LicenseSummary,
    LimitationRecord,
    OAuthCallbackResponse,
    QueryContext,
    SearchResponse,
    TokenCreateRequest,
    TokenCreateResponse,
    TokenExpirationResponse,
)

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

_APP_URL: str = APP_URL  # type: ignore[assignment]
_GITHUB_OAUTH_CLIENT_ID: str = GITHUB_OAUTH_CLIENT_ID  # type: ignore[assignment]
_GITHUB_OAUTH_CLIENT_SECRET: str = GITHUB_OAUTH_CLIENT_SECRET  # type: ignore[assignment]

EULA_VERSION = "demo-v1"
EULA_PATH = Path(__file__).resolve().parent / "docs" / "eula-demo-v1.md"
try:
    EULA_CONTENT = EULA_PATH.read_text(encoding="utf-8")
except FileNotFoundError as exc:
    raise RuntimeError(f"Required EULA file is missing: {EULA_PATH}") from exc

app = FastAPI()
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
for _name in ("azure_oracle.request", "azure_oracle.error"):
    _logger = logging.getLogger(_name)
    _logger.setLevel(logging.INFO)
    _logger.addHandler(_stream_handler)
    _logger.propagate = False

allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,healthcheck.railway.app")
allowed_hosts = [host.strip() for host in allowed_hosts_str.split(",")]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.add_middleware(RequestLoggingMiddleware)
logging.getLogger("uvicorn.error").addFilter(SuppressUvicornTracebackFilter())
logging.getLogger("uvicorn.access").addFilter(SuppressUvicornAccessLogFilter())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    start = request.scope.get("state", {}).get("request_start")
    duration_ms = (time.perf_counter() - start) * 1000 if start else 0
    log_request(request.method, request.url.path, 500, duration_ms)
    log_unhandled_exception(exc)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


SessionFactory = create_session_factory()


def get_db() -> Generator[Session, None, None]:
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"
OAUTH_SCOPE = "read:user"
OAUTH_STATE_TTL = timedelta(minutes=10)
AUTH_GRANT_TTL = timedelta(minutes=5)
GITHUB_TIMEOUT = httpx.Timeout(10.0)


def _new_credential() -> str:
    return secrets.token_urlsafe(32)


def _get_bearer_credential(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    credential = authorization.removeprefix("Bearer ")
    if not credential:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return credential


def _find_active_onboarding_grant(db: Session, authorization: str | None) -> AuthGrant:
    credential_hash = hash_token(_get_bearer_credential(authorization))
    grant = db.scalar(
        select(AuthGrant).where(
            AuthGrant.credential_hash == credential_hash,
            AuthGrant.purpose == "onboarding",
            AuthGrant.consumed_at.is_(None),
            AuthGrant.expires_at > datetime.now(UTC),
        )
    )
    if grant is None:
        raise HTTPException(status_code=401, detail="Invalid or expired onboarding credential")
    return grant


def _github_identity(code: str) -> tuple[int, str]:
    try:
        token_response = httpx.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": _GITHUB_OAUTH_CLIENT_ID,
                "client_secret": _GITHUB_OAUTH_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=GITHUB_TIMEOUT,
        )
        if token_response.status_code != 200:
            raise ValueError("GitHub token exchange failed")
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("GitHub token response is malformed")
        user_response = httpx.get(
            GITHUB_USER_API,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=GITHUB_TIMEOUT,
        )
        if user_response.status_code != 200:
            raise ValueError("GitHub user lookup failed")
        github_user = user_response.json()
        github_id = github_user.get("id")
        login = github_user.get("login")
        if not isinstance(github_id, int) or not isinstance(login, str) or not login:
            raise ValueError("GitHub user response is malformed")
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(status_code=502, detail="GitHub OAuth provider failed") from None
    return github_id, login


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/login")
def auth_login(db: Session = Depends(get_db)) -> RedirectResponse:  # noqa: B008
    state = _new_credential()
    db.add(OAuthState(state_hash=hash_token(state), expires_at=datetime.now(UTC) + OAUTH_STATE_TTL))
    db.commit()
    params = {
        "client_id": _GITHUB_OAUTH_CLIENT_ID,
        "redirect_uri": f"{_APP_URL}/auth/callback",
        "state": state,
        "scope": OAUTH_SCOPE,
    }
    query_string = "&".join(f"{key}={value}" for key, value in params.items())
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{query_string}", status_code=302)


@app.get("/auth/callback", response_model=OAuthCallbackResponse)
def auth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),  # noqa: B008
) -> OAuthCallbackResponse:
    state_hash = hash_token(state)
    state_row = db.scalar(
        select(OAuthState).where(
            OAuthState.state_hash == state_hash,
            OAuthState.consumed_at.is_(None),
            OAuthState.expires_at > datetime.now(UTC),
        )
    )
    if state_row is None:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    github_id, login = _github_identity(code)
    now = datetime.now(UTC)
    onboarding_credential = _new_credential()
    onboarding_expires_at = now + AUTH_GRANT_TTL
    try:
        claimed_state = db.execute(
            update(OAuthState)
            .where(
                OAuthState.id == state_row.id,
                OAuthState.consumed_at.is_(None),
                OAuthState.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(OAuthState.id)
        ).scalar_one_or_none()
        if claimed_state is None:
            db.rollback()
            raise HTTPException(status_code=400, detail="Invalid OAuth state")
        user_id = db.execute(
            insert(User)
            .values(github_id=github_id, login=login)
            .on_conflict_do_update(
                index_elements=[User.github_id],
                set_={"login": login},
            )
            .returning(User.id)
        ).scalar_one()
        db.add(
            AuthGrant(
                user_id=user_id,
                credential_hash=hash_token(onboarding_credential),
                purpose="onboarding",
                expires_at=onboarding_expires_at,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from None
    return OAuthCallbackResponse(
        next_action="accept_eula",
        login=login,
        onboarding_credential=onboarding_credential,
        onboarding_expires_at=onboarding_expires_at,
    )


@app.get("/auth/eula", response_model=EulaDocumentResponse)
def auth_eula(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),  # noqa: B008
) -> EulaDocumentResponse:
    _find_active_onboarding_grant(db, authorization)
    return EulaDocumentResponse(version=EULA_VERSION, content=EULA_CONTENT)


@app.post("/auth/eula/accept", response_model=EulaAcceptanceResponse)
def accept_eula(
    payload: EulaAcceptanceRequest,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),  # noqa: B008
) -> EulaAcceptanceResponse:
    grant = _find_active_onboarding_grant(db, authorization)
    if payload.version != EULA_VERSION:
        raise HTTPException(status_code=409, detail="EULA version does not match current terms")
    now = datetime.now(UTC)
    issuance_credential = _new_credential()
    issuance_expires_at = now + AUTH_GRANT_TTL
    try:
        claimed_grant = db.execute(
            update(AuthGrant)
            .where(
                AuthGrant.id == grant.id,
                AuthGrant.consumed_at.is_(None),
                AuthGrant.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(AuthGrant.user_id)
        ).scalar_one_or_none()
        if claimed_grant is None:
            db.rollback()
            raise HTTPException(status_code=401, detail="Invalid or expired onboarding credential")
        user = db.scalar(select(User).where(User.id == claimed_grant).with_for_update())
        if user is None:
            db.rollback()
            raise HTTPException(status_code=401, detail="Invalid or expired onboarding credential")
        if user.eula_version != EULA_VERSION or user.eula_accepted_at is None:
            user.eula_version = EULA_VERSION
            user.eula_accepted_at = now
            db.add(LifecycleEvent(user_id=user.id, event_type="eula_accepted", metadata_json=f'{{"eula_version":"{EULA_VERSION}"}}'))
        active_license = db.scalar(
            select(License).where(License.user_id == user.id, License.is_active.is_(True))
        )
        if active_license is None:
            active_license = License(user_id=user.id, license_type="demo", is_active=True)
            db.add(active_license)
            db.add(LifecycleEvent(user_id=user.id, event_type="demo_license_assigned", metadata_json='{"license_type":"demo"}'))
            db.flush()
        db.add(
            AuthGrant(
                user_id=user.id,
                credential_hash=hash_token(issuance_credential),
                purpose="token_issuance",
                expires_at=issuance_expires_at,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to assign Demo license") from None
    return EulaAcceptanceResponse(
        next_action="create_token",
        license=LicenseSummary(
            license_type=active_license.license_type,
            is_active=active_license.is_active,
            created_at=active_license.created_at,
        ),
        issuance_credential=issuance_credential,
        issuance_expires_at=issuance_expires_at,
    )


@app.post("/auth/tokens", response_model=TokenCreateResponse)
def create_token(
    payload: TokenCreateRequest,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),  # noqa: B008
) -> TokenCreateResponse:
    credential_hash = hash_token(_get_bearer_credential(authorization))
    now = datetime.now(UTC)
    grant = db.scalar(
        select(AuthGrant).where(
            AuthGrant.credential_hash == credential_hash,
            AuthGrant.purpose == "token_issuance",
            AuthGrant.consumed_at.is_(None),
            AuthGrant.expires_at > now,
        )
    )
    if grant is None:
        raise HTTPException(status_code=401, detail="Invalid or expired issuance credential")

    raw_token = _new_credential()
    expires_at = now + timedelta(days=90)
    try:
        claimed_grant = db.execute(
            update(AuthGrant)
            .where(
                AuthGrant.id == grant.id,
                AuthGrant.consumed_at.is_(None),
                AuthGrant.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(AuthGrant.user_id)
        ).scalar_one_or_none()
        if claimed_grant is None:
            db.rollback()
            raise HTTPException(status_code=401, detail="Invalid or expired issuance credential")
        active_demo_license = db.scalars(
            select(License).where(
                License.user_id == claimed_grant,
                License.license_type == "demo",
                License.is_active.is_(True),
            )
        ).first()
        if active_demo_license is None:
            db.rollback()
            raise HTTPException(status_code=403, detail="No active Demo license")
        token = Token(
            user_id=claimed_grant,
            token_hash=hash_token(raw_token),
            name=payload.name,
            expires_at=expires_at,
        )
        db.add(token)
        db.flush()
        db.add(
            LifecycleEvent(
                user_id=claimed_grant,
                event_type="token_created",
                metadata_json=json.dumps({"token_id": str(token.id), "name": token.name}),
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to create token") from None
    return TokenCreateResponse(
        token=raw_token,
        token_id=str(token.id),
        name=token.name,
        expires_at=token.expires_at,
    )


@app.post("/auth/tokens/{token_id}/expire", response_model=TokenExpirationResponse)
def expire_token(
    token_id: str,
    user: User = Depends(require_active_license),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> TokenExpirationResponse:
    try:
        parsed_token_id = UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Token not found") from None
    token = db.scalar(select(Token).where(Token.id == parsed_token_id, Token.user_id == user.id))
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    token.expires_at = datetime.now(UTC)
    db.commit()
    return TokenExpirationResponse(expired=True, token_id=str(token.id), expires_at=token.expires_at)


@app.get("/auth/probe")
def auth_probe(user: User = Depends(require_active_license)) -> dict[str, object]:  # noqa: B008
    return {"authenticated": True, "user": user.login}


@app.get("/limitations/search", response_model=SearchResponse)
def limitations_search(
    q: str = Query(..., min_length=1, max_length=200),
    region: str | None = Query(None, max_length=200),
    sku: str | None = Query(None, max_length=200),
    user: User = Depends(require_active_license),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> SearchResponse:
    resolved_service = resolve_query(q)
    statement = select(Limitation).options(joinedload(Limitation.source)).where(
        Limitation.verification_state == "verified"
    )
    if resolved_service is not None:
        statement = statement.where(Limitation.service == resolved_service)
    else:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(
            Limitation.service.ilike(pattern, escape="\\")
            | Limitation.feature.ilike(pattern, escape="\\")
        )
    statement = statement.order_by(Limitation.service, Limitation.id).limit(500)
    rows = db.scalars(statement).all()
    records = [
        LimitationRecord(
            id=row.id,
            service=row.service,
            feature=row.feature,
            support_status=row.support_status,
            limitation_type=row.limitation_type,
            details=row.details,
            workaround=row.workaround,
            source_url=row.source.url,
            source_title=row.source.title,
            quote=row.quote,
            confidence=row.confidence,
            verification_state=row.verification_state,
            verified_at=row.verified_at,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
        )
        for row in rows
    ]
    return SearchResponse(
        query=QueryContext(q=q, region=region, sku=sku),
        support_status=aggregate_verdict(map_support_status(row.support_status) for row in rows),
        record_count=len(records),
        records=records,
    )
