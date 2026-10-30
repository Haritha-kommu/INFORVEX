
import logging
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .agents.geographical_filtering import normalize_location
from .agents.news_analytics import analyze_articles
from .agents.orchestration import (
    ALL_AGENT_NAMES,
    recover_stale_runs,
    run_collection,
)
from .config import settings
from .database import engine, ensure_schema, get_db
from .geo_reference import GEOGRAPHY, canonical_name, geography_options, resolve_location
from .models import AgentExecution, Article, ArticleAnalytics, CollectionRun, FeedExecution
from .schemas import ArticleResponse, CollectionResponse
from .scheduler import scheduler as collection_scheduler, start_scheduler, stop_scheduler

logging.basicConfig(level=settings.log_level)


def _reference_key(values: dict, value: str | None) -> str | None:
    return canonical_name(values, value)


def _stored_location_values(
    db: Session,
    field,
    *,
    country: str | None = None,
    state: str | None = None,
) -> list[str]:
    """Return non-empty location values already stored on articles."""
    query = db.query(field).filter(field.is_not(None), func.trim(field) != "")
    if country:
        query = query.filter(
            func.lower(func.trim(Article.country)) == country.strip().casefold()
        )
    if state:
        query = query.filter(
            func.lower(func.trim(Article.state)) == state.strip().casefold()
        )

    values = {
        " ".join(value.split())
        for (value,) in query.distinct().all()
        if isinstance(value, str) and value.strip()
    }
    return sorted(values, key=str.casefold)


def _stored_location_label(
    db: Session,
    field,
    value: str,
    *,
    country: str | None = None,
    state: str | None = None,
) -> str | None:
    """Resolve a filter label from an existing article, case-insensitively."""
    query = db.query(field).filter(
        field.is_not(None),
        func.lower(func.trim(field)) == " ".join(value.split()).casefold(),
    )

    if country:
        query = query.filter(
            func.lower(func.trim(Article.country)) == country.strip().casefold()
        )
    if state:
        query = query.filter(
            func.lower(func.trim(Article.state)) == state.strip().casefold()
        )

    row = query.order_by(field).first()
    return (
        " ".join(row[0].split())
        if row and isinstance(row[0], str) and row[0].strip()
        else None
    )


def _merge_location_values(*groups: list[str]) -> list[str]:
    by_key: dict[str, str] = {}

    for group in groups:
        for value in group:
            normalized = " ".join(value.split())
            if normalized:
                by_key.setdefault(normalized.casefold(), normalized)

    return sorted(by_key.values(), key=str.casefold)


def _valid_location_count(db: Session) -> int:
    valid_paths = []

    for country, data in GEOGRAPHY.items():
        country_match = func.lower(func.trim(Article.country)) == country.casefold()

        valid_paths.append(
            and_(
                country_match,
                Article.state.is_(None),
                Article.district.is_(None),
            )
        )

        for state, state_data in data["states"].items():
            districts = (
                state_data.get("districts", [])
                if isinstance(state_data, dict)
                else state_data
            )
            state_match = func.lower(func.trim(Article.state)) == state.casefold()

            valid_paths.append(
                and_(
                    country_match,
                    state_match,
                    Article.district.is_(None),
                )
            )

            for district in districts:
                district_name = (
                    district.get("name")
                    if isinstance(district, dict)
                    else district
                )

                if district_name:
                    valid_paths.append(
                        and_(
                            country_match,
                            state_match,
                            func.lower(func.trim(Article.district))
                            == district_name.casefold(),
                        )
                    )

    return (
        db.query(func.count(Article.id))
        .filter(or_(*valid_paths))
        .scalar()
        or 0
    )


def _utc_boundary(value: date, *, end: bool = False) -> datetime:
    boundary = datetime.combine(
        value + (timedelta(days=1) if end else timedelta(0)),
        time.min,
    )
    return boundary.replace(tzinfo=timezone.utc)


def _require_admin(authorization: str | None) -> None:
    if (
        settings.admin_api_token
        and authorization != f"Bearer {settings.admin_api_token}"
    ):
        raise HTTPException(401, "Administrative authorization is required")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema(engine)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="NewsSphere API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "NewsSphere API"}


@app.get("/api/system/status")
def system_status():
    """Expose non-secret runtime configuration for the Settings monitor."""
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "scheduler_running": collection_scheduler.running,
        "collection_interval_minutes": settings.collection_interval_minutes,
        "configured_feed_count": len(settings.feeds),
    }


@app.get("/api/news")
def list_news(
    db: Session = Depends(get_db),
    search: str | None = None,
    category: str | None = None,
    country: str | None = None,
    state: str | None = None,
    district: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    source: str | None = None,
    date_basis: str = Query("publication", pattern="^(publication|collected)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "start_date cannot be after end_date")

    reference_country = _reference_key(GEOGRAPHY, country) if country else None

    if country and reference_country is None:
        reference_country = _stored_location_label(db, Article.country, country)

        if reference_country is None:
            raise HTTPException(
                422,
                "Country is not present in the reference data or stored article locations",
            )

    if state and not country:
        raise HTTPException(
            422,
            "Select a country before selecting a state/province",
        )

    reference_states = (
        GEOGRAPHY.get(reference_country, {}).get("states", {})
        if reference_country
        else {}
    )
    reference_state = _reference_key(reference_states, state) if state else None

    if state and reference_state is None:
        reference_state = _stored_location_label(
            db,
            Article.state,
            state,
            country=reference_country,
        )

        if reference_state is None:
            raise HTTPException(
                422,
                "State/province is not available for the selected country",
            )

    if district and not state:
        raise HTTPException(
            422,
            "Select a state/province before selecting a district",
        )

    resolved_district = None

    if (
        district
        and reference_country in GEOGRAPHY
        and reference_state in GEOGRAPHY[reference_country]["states"]
    ):
        resolved_district = resolve_location(
            reference_country,
            reference_state,
            district,
        ).get("district")

    if district and resolved_district is None:
        resolved_district = _stored_location_label(
            db,
            Article.district,
            district,
            country=reference_country,
            state=reference_state,
        )

        if resolved_district is None:
            raise HTTPException(
                422,
                "District is not available for the selected state/province",
            )

    query = db.query(Article)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Article.title.ilike(term),
                Article.summary.ilike(term),
            )
        )

    filters = (
        (Article.category, category),
        (Article.country, reference_country),
        (Article.state, reference_state),
        (Article.district, resolved_district),
        (Article.source_name, source),
    )

    for field, value in filters:
        if value:
            query = query.filter(
                func.lower(func.trim(field)) == value.strip().casefold()
            )

    date_column = (
        Article.publication_time
        if date_basis == "publication"
        else Article.first_fetched_at
    )

    if start_date:
        query = query.filter(date_column >= _utc_boundary(start_date))

    if end_date:
        query = query.filter(
            date_column < _utc_boundary(end_date, end=True)
        )

    total = query.count()

    order_column = (
        Article.publication_time
        if date_basis == "publication"
        else Article.first_fetched_at
    )

    articles = (
        query.order_by(
            order_column.desc().nullslast(),
            Article.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            ArticleResponse.model_validate(article)
            for article in articles
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/news/{article_id}", response_model=ArticleResponse)
def get_news(article_id: int, db: Session = Depends(get_db)):
    article = db.get(Article, article_id)

    if not article:
        raise HTTPException(404, "Article not found")

    return article


@app.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    today_start = _utc_boundary(datetime.now(timezone.utc).date())

    category_rows = (
        db.query(Article.category, func.count(Article.id))
        .group_by(Article.category)
        .all()
    )

    return {
        "articles": db.query(func.count(Article.id)).scalar() or 0,
        "sources": db.query(
            func.count(func.distinct(Article.source_name))
        ).scalar() or 0,
        "today": db.query(func.count(Article.id))
        .filter(Article.first_fetched_at >= today_start)
        .scalar() or 0,
        "duplicates": db.query(
            func.coalesce(func.sum(CollectionRun.duplicates), 0)
        ).scalar() or 0,
        "failed": db.query(
            func.coalesce(func.sum(CollectionRun.failed), 0)
        ).scalar() or 0,
        "geographical_coverage": _valid_location_count(db),
        "categories": [
            {"name": name, "value": count}
            for name, count in category_rows
        ],
        "last_collection": db.query(CollectionRun)
        .order_by(CollectionRun.started_at.desc())
        .first(),
    }



@app.get("/api/agents/status")
def agent_status(db: Session = Depends(get_db)):
    recover_stale_runs(db)

    display_names = {
        "News Analytics Agent": "NLP Agent",
    }

    result = []

    for database_name in ALL_AGENT_NAMES:
        display_name = display_names.get(database_name, database_name)
        execution = (
            db.query(AgentExecution)
            .filter_by(agent_name=database_name)
            .order_by(AgentExecution.started_at.desc())
            .first()
        )

        if execution and execution.status == "running":
            last_execution = execution.started_at
        else:
            last_execution = (
                execution.completed_at if execution else None
            )

        result.append({
            "name": display_name,
            "status": execution.status if execution else "idle",
            "run_id": execution.run_id if execution else None,
            "started_at": execution.started_at if execution else None,
            "completed_at": execution.completed_at if execution else None,
            "last_heartbeat_at": execution.last_heartbeat_at if execution else None,
            "last_execution": last_execution,
            "processed_count": execution.processed_count if execution else 0,
            "error": execution.error if execution else None,
        })

    return result



def _analytics_rows(db: Session) -> list[tuple[Article, ArticleAnalytics]]:
    return (
        db.query(Article, ArticleAnalytics)
        .join(
            ArticleAnalytics,
            ArticleAnalytics.article_id == Article.id,
        )
        .order_by(ArticleAnalytics.analyzed_at.desc())
        .all()
    )


@app.get("/api/analytics/summary")
def analytics_summary(db: Session = Depends(get_db)):
    rows = _analytics_rows(db)

    sentiment = {
        name: 0
        for name in ("positive", "neutral", "negative")
    }

    categories: dict[str, int] = {}
    publishers: dict[str, int] = {}
    keywords: Counter[str] = Counter()
    people: Counter[str] = Counter()
    organizations: Counter[str] = Counter()
    daily: Counter[str] = Counter()

    for article, analysis in rows:
        sentiment[analysis.sentiment] = (
            sentiment.get(analysis.sentiment, 0) + 1
        )

        categories[article.category] = (
            categories.get(article.category, 0) + 1
        )

        publishers[article.source_name] = (
            publishers.get(article.source_name, 0) + 1
        )

        analyzed_date = (
            article.publication_time or article.first_fetched_at
        ).date().isoformat()

        daily[analyzed_date] += 1

        for keyword in json.loads(analysis.keywords_json or "[]"):
            keywords[keyword.get("term", "")] += 1

        for entity in json.loads(analysis.entities_json or "[]"):
            if entity.get("label") == "PERSON":
                people[entity.get("text", "")] += 1

            if entity.get("label") == "ORG":
                organizations[entity.get("text", "")] += 1

    latest = (
        db.query(ArticleAnalytics)
        .order_by(ArticleAnalytics.analyzed_at.desc())
        .first()
    )

    return {
        "enabled": settings.analytics_enabled,
        "analyzed_articles": len(rows),
        "total_articles": db.query(func.count(Article.id)).scalar() or 0,
        "sentiment": [
            {"name": name, "value": sentiment[name]}
            for name in sentiment
        ],
        "categories": [
            {"name": name, "value": value}
            for name, value in sorted(
                categories.items(),
                key=lambda item: -item[1],
            )
        ],
        "publishers": [
            {"name": name, "value": value}
            for name, value in sorted(
                publishers.items(),
                key=lambda item: -item[1],
            )[:10]
        ],
        "keywords": [
            {"name": name, "value": value}
            for name, value in keywords.most_common(15)
            if name
        ],
        "people": [
            {"name": name, "value": value}
            for name, value in people.most_common(10)
            if name
        ],
        "organizations": [
            {"name": name, "value": value}
            for name, value in organizations.most_common(10)
            if name
        ],
        "daily_trends": [
            {"date": name, "value": daily[name]}
            for name in sorted(daily)
        ],
        "last_analyzed_at": latest.analyzed_at if latest else None,
        "machine_generated": True,
    }


@app.post("/api/analytics/run")
def analytics_run(
    db: Session = Depends(get_db),
    force: bool = Query(False),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)

    if not settings.analytics_enabled:
        raise HTTPException(
            409,
            "NLP Agent is disabled. Set ANALYTICS_ENABLED=true to enable it.",
        )

    try:
        processed = analyze_articles(db, force=force)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc

    return {
        "status": "completed",
        "processed": processed,
        "force": force,
    }


@app.get("/api/agents/history")
def agent_history(db: Session = Depends(get_db)):
    return (
        db.query(AgentExecution)
        .order_by(AgentExecution.started_at.desc())
        .limit(50)
        .all()
    )


@app.get("/api/collection/history")
def collection_history(db: Session = Depends(get_db)):
    recover_stale_runs(db)

    return (
        db.query(CollectionRun)
        .order_by(CollectionRun.started_at.desc())
        .limit(50)
        .all()
    )


@app.get("/api/collection/status")
def collection_status(db: Session = Depends(get_db)):
    recover_stale_runs(db)

    run = (
        db.query(CollectionRun)
        .order_by(CollectionRun.started_at.desc())
        .first()
    )

    if not run:
        return {"status": "idle", "run_id": None}

    return {
        "status": run.status,
        "run_id": run.id,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "last_heartbeat_at": run.last_heartbeat_at,
        "retrieved": run.retrieved,
        "inserted": run.inserted,
        "duplicates": run.duplicates,
        "failed": run.failed,
        "error": run.error,
    }


@app.post("/api/collection/run", response_model=CollectionResponse)
def collection_run(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)

    try:
        run = run_collection(db)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc

    errors = [run.error] if run.error else []

    return CollectionResponse(
        status=run.status,
        run_id=run.id,
        retrieved=run.retrieved,
        inserted=run.inserted,
        duplicates=run.duplicates,
        failed=run.failed,
        errors=errors,
    )


@app.get("/api/sources")
def sources(db: Session = Depends(get_db)):
    latest_by_url = {}

    for execution in (
        db.query(FeedExecution)
        .order_by(FeedExecution.checked_at.desc())
        .all()
    ):
        latest_by_url.setdefault(execution.feed_url, execution)

    article_counts: dict[str, int] = {}

    for source_name, count in (
        db.query(Article.source_name, func.count(Article.id))
        .group_by(Article.source_name)
        .all()
    ):
        normalized_name = source_name.strip() if source_name else source_name

        if normalized_name:
            key = normalized_name.casefold()
            article_counts[key] = article_counts.get(key, 0) + count

    configured = [
        {
            "url": feed_url,
            "name": (
                latest_by_url[feed_url].source_name.strip()
                if feed_url in latest_by_url
                and latest_by_url[feed_url].source_name
                else feed_url
            ),
            "status": (
                latest_by_url[feed_url].status
                if feed_url in latest_by_url
                else "not_checked"
            ),
            "articles": (
                article_counts.get(
                    latest_by_url[feed_url].source_name.strip().casefold(),
                    0,
                )
                if feed_url in latest_by_url
                and latest_by_url[feed_url].source_name
                else 0
            ),
            "retrieved": (
                latest_by_url[feed_url].article_count
                if feed_url in latest_by_url
                else 0
            ),
            "inserted": (
                latest_by_url[feed_url].inserted_count
                if feed_url in latest_by_url
                else 0
            ),
            "duplicates": (
                latest_by_url[feed_url].duplicate_count
                if feed_url in latest_by_url
                else 0
            ),
            "error": (
                latest_by_url[feed_url].error
                if feed_url in latest_by_url
                else None
            ),
            "last_checked": (
                latest_by_url[feed_url].checked_at
                if feed_url in latest_by_url
                else None
            ),
        }
        for feed_url in settings.feeds
    ]

    configured_names = {
        item["name"].strip().casefold()
        for item in configured
        if item["name"]
    }

    article_sources = (
        db.query(Article.source_name, func.count(Article.id))
        .group_by(Article.source_name)
        .all()
    )

    configured.extend(
        {
            "url": f"article-source:{name}",
            "name": name,
            "status": "stored_only",
            "articles": count,
            "retrieved": 0,
            "inserted": 0,
            "duplicates": 0,
            "error": None,
            "last_checked": None,
        }
        for name, count in article_sources
        if name and name.strip().casefold() not in configured_names
    )

    return configured


@app.get("/api/geo/options")
def geo_options_endpoint(
    country: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """Return reference choices plus location names already stored on articles."""
    requested_country = country
    country_key = (
        _reference_key(GEOGRAPHY, requested_country)
        if requested_country
        else None
    )

    if requested_country and country_key is None:
        country_key = _stored_location_label(
            db,
            Article.country,
            requested_country,
        )

        if country_key is None:
            raise HTTPException(
                422,
                "Country is not present in the reference data or stored article locations",
            )

    country = country_key

    if state and not country:
        raise HTTPException(
            422,
            "Select a country before selecting a state/province",
        )

    reference_states = (
        GEOGRAPHY.get(country, {}).get("states", {})
        if country
        else {}
    )

    requested_state = state
    state_key = (
        _reference_key(reference_states, requested_state)
        if requested_state
        else None
    )

    if requested_state and state_key is None:
        state_key = _stored_location_label(
            db,
            Article.state,
            requested_state,
            country=country,
        )

        if state_key is None:
            raise HTTPException(
                422,
                "State/province is not available for the selected country",
            )

    state = state_key

    if country in GEOGRAPHY:
        reference_options = geography_options(country, state)
    else:
        reference_options = {
            "countries": sorted(GEOGRAPHY),
            "states": [],
            "districts": [],
        }

    countries = _merge_location_values(
        reference_options["countries"],
        _stored_location_values(db, Article.country),
    )

    states = reference_options["states"]
    districts = reference_options["districts"]

    if country:
        states = _merge_location_values(
            states,
            _stored_location_values(
                db,
                Article.state,
                country=country,
            ),
        )

    if country and state:
        districts = _merge_location_values(
            districts,
            _stored_location_values(
                db,
                Article.district,
                country=country,
                state=state,
            ),
        )

    return {
        "countries": countries,
        "states": states,
        "districts": districts,
        "coverage": "Reference hierarchy plus locations already stored on articles",
        "source": "backend/data/geography.json and stored article metadata",
    }


@app.post("/api/news/reclassify")
def reclassify(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)

    from .agents.news_segregation import classify_article

    articles = db.query(Article).all()

    for article in articles:
        article.category, article.category_explanation = classify_article(
            article.title,
            article.summary,
        )

    db.commit()

    return {"updated": len(articles)}


@app.post("/api/news/enrich-locations")
def enrich_locations(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    """Retry only unknown locations using the traceable conservative resolver."""
    _require_admin(authorization)

    from .agents.geographical_filtering import apply_location_enrichment

    updated = 0
    examined = 0

    for article in (
        db.query(Article)
        .filter(Article.location_provenance == "unknown")
        .yield_per(100)
    ):
        examined += 1

        result = apply_location_enrichment(
            article,
            {
                "title": article.title,
                "summary": article.summary,
            },
        )

        if result.get("location_provenance") != "unknown":
            updated += 1

    db.commit()

    return {
        "examined": examined,
        "updated": updated,
    }
