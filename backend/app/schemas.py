from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ArticleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    canonical_url: str = Field(min_length=1, max_length=2000)
    source_name: str = Field(min_length=1, max_length=200)
    summary: str | None = None
    content: str | None = None
    country: str | None = None
    state: str | None = None
    district: str | None = None
    location_provenance: str = "unknown"
    publication_time: datetime | None = None


class ArticleResponse(ArticleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url_hash: str
    category: str
    category_explanation: str
    location_confidence: str | None
    first_fetched_at: datetime

    @field_serializer("publication_time", "first_fetched_at")
    def serialize_utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CollectionResponse(BaseModel):
    status: str
    run_id: int
    retrieved: int
    inserted: int
    duplicates: int
    failed: int
    errors: list[str] = Field(default_factory=list)
