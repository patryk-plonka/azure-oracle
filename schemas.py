from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


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
