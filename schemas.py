from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class LimitationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    service: str
    feature: str | None
    support_status: str
    limitation_type: str
    details: str | None
    workaround: str | None
    source_url: str
    source_title: str
    quote: str
    confidence: str
    verification_state: str
    verified_at: datetime
    first_seen: date | None
    last_seen: date | None


class QueryContext(BaseModel):
    q: str
    region: str | None
    sku: str | None
    note: str = "Region and SKU are echoed but not applied as filters in v1."


class SearchResponse(BaseModel):
    query: QueryContext
    support_status: str
    record_count: int
    records: list[LimitationRecord]


class OAuthCallbackResponse(BaseModel):
    next_action: str
    login: str
    onboarding_credential: str
    onboarding_expires_at: datetime


class EulaDocumentResponse(BaseModel):
    version: str
    content: str


class EulaAcceptanceRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)


class LicenseSummary(BaseModel):
    license_type: str
    is_active: bool
    created_at: datetime


class EulaAcceptanceResponse(BaseModel):
    next_action: str
    license: LicenseSummary
    issuance_credential: str
    issuance_expires_at: datetime


class TokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TokenCreateResponse(BaseModel):
    token: str
    token_id: str
    name: str
    expires_at: datetime


class TokenExpirationResponse(BaseModel):
    expired: bool
    token_id: str
    expires_at: datetime
