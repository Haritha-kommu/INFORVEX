from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from sqlalchemy.dialects.postgresql import JSONB


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_articles_url_hash"),
        Index("ix_articles_publication_time", "publication_time"),
        Index("ix_articles_category", "category"),
        Index("ix_articles_location", "country", "state", "district"),
        Index("ix_articles_source", "source_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    canonical_url: Mapped[str] = mapped_column(String(2000))
    url_hash: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(40), default="Other")
    category_explanation: Mapped[str] = mapped_column(String(300), default="No category keyword matched")
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location_provenance: Mapped[str] = mapped_column(String(30), default="unknown")
    location_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    publication_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ArticleAnalytics(Base):
    __tablename__ = "article_analytics"
    __table_args__ = (
        UniqueConstraint("article_id", name="uq_article_analytics_article_id"),
        Index("ix_article_analytics_sentiment", "sentiment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sentiment: Mapped[str] = mapped_column(String(20))
    sentiment_score: Mapped[float] = mapped_column(default=0.0)
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    entities_json: Mapped[str] = mapped_column(Text, default="[]")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    analyzer_version: Mapped[str] = mapped_column(String(80), default="vader-tfidf-spacy")


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    retrieved: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeedExecution(Base):
    __tablename__ = "feed_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_url: Mapped[str] = mapped_column(String(2000), index=True)
    source_name: Mapped[str] = mapped_column(String(200), default="Unknown source")
    status: Mapped[str] = mapped_column(String(30))
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CollectionLock(Base):
    __tablename__ = "collection_lock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class GeographyReference(Base):
    __tablename__ = "geography_reference"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(
        String(30),
        default="1.0",
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )