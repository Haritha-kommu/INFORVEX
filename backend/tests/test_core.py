from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.agents import orchestration
from app.agents.database_management import normalize_url, store_article
from app.agents.geographical_filtering import matches_location
from app.agents.geographical_filtering import enrich_location, has_valid_location
from app.agents.news_segregation import classify_article
from app.agents.web_news_scraping import collect_feeds
from app.agents import web_news_scraping
from app.config import _bool_setting
from app.database import Base, get_db
from app.models import AgentExecution, Article, CollectionLock, CollectionRun


@pytest.fixture
def database(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(main, "engine", test_engine)
    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as client:
        yield client, test_session
    main.app.dependency_overrides.clear()
    test_engine.dispose()


def article_data(url="https://example.com/story", **overrides):
    data = {
        "title": "Technology research update",
        "canonical_url": url,
        "source_name": "Example News",
        "summary": "New software research was announced.",
        "country": "India",
        "state": "Karnataka",
        "district": "Bengaluru Urban",
        "publication_time": datetime.now(timezone.utc),
        "location_provenance": "source",
    }
    return {**data, **overrides}


def test_health_endpoint(database):
    client, _ = database
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_status_endpoint_exposes_safe_scheduler_metadata(database):
    client, _ = database
    response = client.get("/api/system/status")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["scheduler_enabled"], bool)
    assert isinstance(payload["scheduler_running"], bool)
    assert isinstance(payload["collection_interval_minutes"], int)
    assert isinstance(payload["configured_feed_count"], int)
    assert "admin_api_token" not in payload


def test_agent_status_lists_all_six_agents_before_execution(database):
    client, _ = database

    response = client.get("/api/agents/status")

    assert response.status_code == 200
    assert [(item["name"], item["status"]) for item in response.json()] == [
        ("Orchestration Agent", "idle"),
        ("Web News Scraping Agent", "idle"),
        ("Database Management Agent", "idle"),
        ("News Segregation Agent", "idle"),
        ("Geographical Filtering Agent", "idle"),
        ("NLP Agent", "idle"),
    ]


def test_analytics_is_enabled_when_setting_is_unset(monkeypatch):
    monkeypatch.delenv("ANALYTICS_ENABLED", raising=False)

    assert _bool_setting("ANALYTICS_ENABLED", "true") is True


def test_database_initialization_and_duplicate_urls(database):
    _, session_factory = database
    with session_factory() as db:
        outcome, article = store_article(db, article_data("HTTPS://Example.com/story/"))
        db.commit()
        duplicate, _ = store_article(db, article_data("https://example.com/story"))
        db.commit()
        assert outcome == "inserted"
        assert duplicate == "duplicate"
        assert db.query(Article).count() == 1
        assert article.url_hash


def test_category_classification_and_explanation():
    category, explanation = classify_article("Election policy announced")
    assert category == "Politics"
    assert "election" in explanation
    assert classify_article("Quarterly earnings and revenue rise")[0] == "Business"
    assert classify_article("Championship cricket match begins")[0] == "Sports"
    assert classify_article("New cancer medicine approved")[0] == "Health"
    assert classify_article("Film festival announces lineup")[0] == "Entertainment"
    assert classify_article("Astronomy research discovers exoplanet")[0] == "Science"
    assert classify_article("A headline without known keywords")[0] == "Other"
        # A mobile app mentioned in a murder-trial summary
    # must not make the article Technology news.
    assert classify_article(
        "Double murder trial continues",
        "Police evidence mentions a mobile app",
    )[0] == "Other"

    # The headline's Education category takes priority
    # over an unrelated Technology keyword in the summary.
    assert classify_article(
        "School students win spelling bee",
        "A smartphone is used during the event",
    )[0] == "Education"


def test_url_normalization():
    assert normalize_url("HTTPS://Example.com/story/?utm_source=x") == "https://example.com/story?utm_source=x"


def test_article_filters_and_date_range(database):
    client, session_factory = database
    with session_factory() as db:
        old = article_data(
            "https://example.com/old",
            title="Old health report",
            source_name="Health Desk",
            country="United States",
            state="California",
            district="Los Angeles County",
            publication_time=datetime.now(timezone.utc) - timedelta(days=10),
        )
        new = article_data("https://example.com/new")
        for item in (old, new):
            store_article(db, item)
        db.commit()
    response = client.get("/api/news", params={
        "country": "india", "state": "Karnataka", "district": "Bengaluru Urban",
        "category": "technology", "source": "example news",
        "start_date": (datetime.now().date() - timedelta(days=1)).isoformat(),
        "end_date": datetime.now().date().isoformat(),
    })
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert client.get("/api/news", params={"start_date": "2026-02-02", "end_date": "2026-02-01"}).status_code == 422


def test_geography_reference_is_independent_of_articles(database):
    client, _ = database
    response = client.get("/api/geo/options", params={"country": "India", "state": "Karnataka"})
    assert response.status_code == 200
    assert {"Bengaluru Urban", "Mysuru"}.issubset(
        set(client.get("/api/geo/options", params={"country": "India", "state": "Karnataka"}).json()["districts"])
    )
    assert client.get("/api/geo/options", params={"state": "Karnataka"}).status_code == 422
    assert client.get("/api/geo/options", params={"country": "Unknown"}).status_code == 422


def test_geography_filter_keeps_unknown_locations_unmatched():
    unknown = Article(country=None, state=None, district=None)
    known = Article(country="India", state="Karnataka", district="Bengaluru Urban")
    assert matches_location(known, country=" india ", state="KARNATAKA")
    assert not matches_location(unknown, country="India")


def test_geography_enrichment_requires_explicit_or_unambiguous_metadata():
    explicit = enrich_location({
        "title": "Local update",
        "summary": None,
        "country": "India",
        "state": "Karnataka",
        "district": "Bengaluru Urban",
    })
    assert explicit["location_provenance"] == "source"
    assert explicit["location_confidence"] == "high"

    inferred = enrich_location({
        "title": "Explosion in Bengaluru Urban",
        "summary": "Officials in India confirmed the incident.",
    })
    assert inferred["country"] == "India"
    assert inferred["state"] == "Karnataka"
    assert inferred["district"] == "Bengaluru Urban"
    assert inferred["location_provenance"] == "context_reference"
    assert inferred["location_confidence"] == "medium"

    mentioned_only = enrich_location({
        "title": "Report compares Bengaluru Urban and Mumbai technology sectors",
        "summary": None,
    })
    assert mentioned_only["location_provenance"] == "unknown"

    ambiguous = enrich_location({"title": "Explosion in Springfield", "summary": None})
    assert ambiguous["location_provenance"] == "unknown"
    assert "country" not in ambiguous


def test_structured_event_location_is_preferred_over_feed_metadata():
    result = enrich_location({
        "title": "Publisher headquarters update",
        "summary": "A report was published.",
        "feed": {"title": "India"},
        "location": {"country": "India", "state": "Maharashtra", "district": "Pune"},
    })
    assert result["country"] == "India"
    assert result["state"] == "Maharashtra"
    assert result["district"] == "Pune"
    assert result["location_provenance"] == "source"
    assert result["location_resolution_reason"] == "structured event-location metadata"


def test_reference_contains_all_country_names_but_partial_admin_coverage():
    from app.geo_reference import GEOGRAPHY

    assert len(GEOGRAPHY) >= 249
    assert "Andhra Pradesh" in GEOGRAPHY["India"]["states"]
    assert "Telangana" in GEOGRAPHY["India"]["states"]
    assert "Guntur" in {
        item.get("name") if isinstance(item, dict) else item
        for item in GEOGRAPHY["India"]["states"]["Andhra Pradesh"]["districts"]
    }
    assert "Pune" in {
        item.get("name") if isinstance(item, dict) else item
        for item in GEOGRAPHY["India"]["states"]["Maharashtra"]["districts"]
    }
    assert len(GEOGRAPHY["Brazil"]["states"]) == 27
    assert len(GEOGRAPHY["France"]["states"]) == 13
    assert len(GEOGRAPHY["Australia"]["states"]) == 9


def test_location_coverage_requires_valid_country_hierarchy():
    valid = Article(country="India", state="Karnataka", district="Mysuru")
    invalid = Article(country="India", state="Karnataka", district="Unknown District")
    unknown = Article(country=None)
    explicit_unknown = Article(country="Unknown")
    assert has_valid_location(valid)
    assert not has_valid_location(invalid)
    assert not has_valid_location(unknown)
    assert not has_valid_location(explicit_unknown)


def test_dashboard_coverage_counts_only_valid_locations(database):
    client, session_factory = database
    with session_factory() as db:
        store_article(db, article_data("https://example.com/valid"))
        store_article(db, article_data(
            "https://example.com/unknown",
            country="Unknown",
            state=None,
            district=None,
        ))
        db.commit()
    assert client.get("/api/dashboard/stats").json()["geographical_coverage"] == 1


def test_existing_article_enrichment_is_repeatable_and_preserves_unknowns(database):
    client, session_factory = database
    with session_factory() as db:
        store_article(db, article_data(
            "https://example.com/enrich",
            title="Flooding in Pune",
            summary="Officials in India reported the event.",
            country=None,
            state=None,
            district=None,
            location_provenance="unknown",
        ))
        store_article(db, article_data(
            "https://example.com/ambiguous",
            title="Report mentions Pune and Mumbai",
            summary=None,
            country=None,
            state=None,
            district=None,
            location_provenance="unknown",
        ))
        db.commit()
    first = client.post("/api/news/enrich-locations")
    assert first.json() == {"examined": 2, "updated": 1}
    second = client.post("/api/news/enrich-locations")
    assert second.json() == {"examined": 1, "updated": 0}
    with session_factory() as db:
        enriched = db.query(Article).filter_by(canonical_url="https://example.com/enrich").one()
        ambiguous = db.query(Article).filter_by(canonical_url="https://example.com/ambiguous").one()
        assert (enriched.country, enriched.state, enriched.district) == ("India", "Maharashtra", "Pune")
        assert ambiguous.country is None


def test_geographic_filter_combines_with_source_and_date(database):
    client, session_factory = database
    with session_factory() as db:
        store_article(db, article_data(
            "https://example.com/geo-match",
            source_name="Regional Desk",
            title="Pune health update",
            summary="Doctors reported a public health event.",
            category="Health",
            publication_time=datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc),
            country="India",
            state="Maharashtra",
            district="Pune",
        ))
        store_article(db, article_data(
            "https://example.com/geo-other",
            source_name="Other Desk",
            publication_time=datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc),
            country="India",
            state="Maharashtra",
            district="Mumbai",
        ))
        db.commit()
    response = client.get("/api/news", params={
        "country": "India", "state": "Maharashtra", "district": "Pune",
        "source": "regional desk", "category": "health",
        "start_date": "2026-10-27", "end_date": "2026-10-27",
    })
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["canonical_url"] == "https://example.com/geo-match"


def test_geography_options_and_filters_include_stored_admin_values(database):
    client, session_factory = database
    with session_factory() as db:
        store_article(db, article_data(
            "https://example.com/andhra-guntur",
            title="Local incident in Guntur",
            country="India",
            state="Andhra Pradesh",
            district="Guntur",
        ))
        db.commit()

    states = client.get("/api/geo/options", params={"country": "India"})
    assert states.status_code == 200
    assert "Andhra Pradesh" in states.json()["states"]

    districts = client.get(
        "/api/geo/options", params={"country": "India", "state": "Andhra Pradesh"}
    )
    assert districts.status_code == 200
    assert "Guntur" in districts.json()["districts"]

    filtered = client.get("/api/news", params={
        "country": "India", "state": "Andhra Pradesh", "district": "Guntur",
    })
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["canonical_url"] == "https://example.com/andhra-guntur"


def test_empty_feed_configuration_is_explicit():
    result = collect_feeds(())
    assert result["articles"] == []
    assert result["message"] == "No feeds configured"


def test_scraper_reports_timeout_and_parses_publication_date(monkeypatch):
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Test Feed</title>
    <item><title>Technology update</title><link>https://example.com/a</link>
    <description>A summary</description><pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""

    class Response:
        content = xml

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        assert kwargs["timeout"].connect == 2.0
        if url == "timeout":
            raise httpx.TimeoutException("timed out")
        return Response()

    monkeypatch.setattr(web_news_scraping.httpx, "get", fake_get)
    result = collect_feeds(("good", "timeout"), timeout_seconds=2.0)
    assert len(result["articles"]) == 1
    assert result["successful"] == [{
        "feed_url": "good",
        "source_name": "Test Feed",
        "status": "success",
        "article_count": 1,
    }]
    assert result["articles"][0]["summary"] == "A summary"
    assert result["articles"][0]["publication_time"].tzinfo == timezone.utc
    assert result["failed"] == [{"feed": "timeout", "error": "timed out"}]


def test_scraper_parses_iso_offset_and_preserves_missing_date(monkeypatch):
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>ISO Feed</title>
    <item><title>Offset story</title><link>https://example.com/offset</link>
    <pubDate>2026-10-27T00:30:00+05:30</pubDate></item>
    <item><title>No date story</title><link>https://example.com/no-date</link></item>
    </channel></rss>"""

    class Response:
        content = xml
        def raise_for_status(self):
            return None

    monkeypatch.setattr(web_news_scraping.httpx, "get", lambda url, **kwargs: Response())
    result = collect_feeds(("iso",))
    by_url = {item["canonical_url"]: item for item in result["articles"]}
    assert by_url["https://example.com/offset"]["publication_time"] == datetime(2026, 10, 26, 19, 0, tzinfo=timezone.utc)
    assert by_url["https://example.com/no-date"]["publication_time"] is None


def test_source_filter_and_inclusive_utc_date_boundaries(database):
    client, session_factory = database
    boundary = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)
    with session_factory() as db:
        store_article(db, article_data("https://example.com/source-a", source_name="Source A", publication_time=boundary))
        store_article(db, article_data("https://example.com/source-b", source_name="Source B", publication_time=boundary))
        db.commit()
    response = client.get("/api/news", params={
        "source": " source a ", "start_date": "2026-10-27", "end_date": "2026-10-27",
    })
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["publication_time"] == "2026-10-27T00:00:00Z"
    collected = client.get("/api/news", params={
        "date_basis": "collected", "start_date": "2020-01-01", "end_date": "2099-12-31",
    })
    assert collected.status_code == 200
    assert collected.json()["total"] == 2


def test_collected_date_basis_orders_by_collection_time(database):
    client, session_factory = database
    with session_factory() as db:
        older_publication = article_data(
            "https://example.com/collected-old",
            publication_time=datetime(2026, 10, 27, 12, tzinfo=timezone.utc),
        )
        newer_publication = article_data(
            "https://example.com/collected-new",
            publication_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        )
        first, first_article = store_article(db, older_publication)
        second, second_article = store_article(db, newer_publication)
        assert first == second == "inserted"
        first_article.first_fetched_at = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
        second_article.first_fetched_at = datetime(2026, 10, 2, 1, tzinfo=timezone.utc)
        db.commit()
    response = client.get("/api/news", params={"date_basis": "collected"})
    assert response.json()["items"][0]["canonical_url"] == "https://example.com/collected-new"


def test_admin_token_protects_collection_when_configured(database, monkeypatch):
    client, _ = database
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_api_token="test-token"))
    monkeypatch.setattr(orchestration, "settings", replace(orchestration.settings, feeds=()))
    assert client.post("/api/collection/run").status_code == 401
    assert client.post("/api/collection/run", headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_partial_collection_records_truthful_statuses(database, monkeypatch):
    client, _ = database
    configured = replace(
    orchestration.settings,
    feeds=("good", "bad"),
    analytics_enabled=False,
)
    monkeypatch.setattr(
        orchestration,
        "settings",
        configured,
    )
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(
        orchestration,
        "collect_feeds",
        lambda feeds: {
            "articles": [article_data("https://example.com/one")],
            "successful": [{"feed_url": "good", "source_name": "Good Feed", "status": "success", "article_count": 1}],
            "failed": [{"feed": "bad", "error": "timeout"}],
        },
    )
    response = client.post("/api/collection/run")
    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_errors"
    statuses = {item["name"]: item["status"] for item in client.get("/api/agents/status").json()}
    assert statuses == {
        "Orchestration Agent": "completed_with_errors",
        "Web News Scraping Agent": "partial",
        "Database Management Agent": "completed",
        "News Segregation Agent": "completed",
        "Geographical Filtering Agent": "completed",
        "NLP Agent": "idle",
    }
    sources = client.get("/api/sources").json()
    assert {source["url"]: source["status"] for source in sources if source["url"] in {"good", "bad"}} == {
        "good": "success",
        "bad": "failed",
    }


def test_analytics_success_records_sixth_agent_without_changing_core_status(database, monkeypatch):
    client, session_factory = database
    configured = replace(orchestration.settings, feeds=("good",), analytics_enabled=True)
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/analytics-success")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [],
    })
    monkeypatch.setattr(orchestration, "analyze_articles", lambda db, article_ids: len(article_ids))

    response = client.post("/api/collection/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    with session_factory() as db:
        analytics = db.query(AgentExecution).filter_by(agent_name="News Analytics Agent").one()
        assert analytics.status == "completed"
        assert analytics.processed_count == 1


def test_analytics_failure_is_warning_and_preserves_collected_article(database, monkeypatch):
    client, session_factory = database
    configured = replace(orchestration.settings, feeds=("good",), analytics_enabled=True)
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/analytics-failure")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [],
    })

    def fail_analytics(db, article_ids):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(orchestration, "analyze_articles", fail_analytics)

    response = client.post("/api/collection/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed_with_warnings"
    assert payload["errors"] == ["News Analytics Agent: model unavailable"]
    with session_factory() as db:
        assert db.query(Article).filter_by(canonical_url="https://example.com/analytics-failure").count() == 1
        analytics = db.query(AgentExecution).filter_by(agent_name="News Analytics Agent").one()
        assert analytics.status == "failed"
        assert analytics.error == "model unavailable"
        run = db.query(CollectionRun).one()
        assert run.status == "completed_with_warnings"
        assert run.error == "News Analytics Agent: model unavailable"


def test_explicitly_disabled_analytics_is_reported_without_hiding_agent(
    database,
    monkeypatch,
):
    client, session_factory = database
    configured = replace(orchestration.settings, feeds=("good",), analytics_enabled=False)
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/analytics-disabled")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [],
    })

    response = client.post("/api/collection/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    statuses = {
        item["name"]: item["status"]
        for item in client.get("/api/agents/status").json()
    }
    assert set(statuses) == {
        "Orchestration Agent",
        "Web News Scraping Agent",
        "Database Management Agent",
        "News Segregation Agent",
        "Geographical Filtering Agent",
        "NLP Agent",
    }
    assert statuses["NLP Agent"] == "idle"
    with session_factory() as db:
        assert db.query(AgentExecution).filter_by(agent_name="News Analytics Agent").count() == 0


def test_core_scraping_failure_keeps_error_status_semantics_when_analytics_enabled(database, monkeypatch):
    client, session_factory = database
    configured = replace(orchestration.settings, feeds=("good", "bad"), analytics_enabled=True)
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/core-failure")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [{"feed": "bad", "error": "timeout"}],
    })
    monkeypatch.setattr(orchestration, "analyze_articles", lambda db, article_ids: len(article_ids))

    response = client.post("/api/collection/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_errors"
    assert response.json()["errors"] == ["bad: timeout"]
    with session_factory() as db:
        assert db.query(CollectionRun).one().status == "completed_with_errors"
        assert db.query(AgentExecution).filter_by(agent_name="News Analytics Agent").one().status == "completed"


def test_repeated_collection_does_not_insert_duplicate(database, monkeypatch):
    client, _ = database
    monkeypatch.setattr(
        orchestration,
        "settings",
        replace(orchestration.settings, feeds=("good",)),
    )
    monkeypatch.setattr(
        orchestration,
        "collect_feeds",
        lambda feeds: {
            "articles": [article_data("https://example.com/repeat/")],
            "successful": [{"feed_url": "good", "source_name": "Good Feed", "status": "success", "article_count": 1}],
            "failed": [],
        },
    )
    assert client.post("/api/collection/run").json()["inserted"] == 1
    second = client.post("/api/collection/run").json()
    assert second["inserted"] == 0
    assert second["duplicates"] == 1


def test_geography_exception_finishes_every_agent_and_releases_lock(database, monkeypatch):
    client, session_factory = database
    configured = replace(orchestration.settings, feeds=("good",))
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/geo-failure")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [],
    })
    monkeypatch.setattr(
        orchestration,
        "apply_location_enrichment",
        lambda article, item: (_ for _ in ()).throw(ValueError("reference unavailable")),
    )

    response = client.post("/api/collection/run")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "Geographical Filtering Agent failed" in response.json()["errors"][0]
    with session_factory() as db:
        run = db.get(CollectionRun, response.json()["run_id"])
        lock = db.get(CollectionLock, 1)
        assert run.completed_at is not None
        assert run.status == "failed"
        assert lock.run_id is None
        executions = db.query(AgentExecution).filter_by(run_id=run.id).all()
        assert all(execution.completed_at is not None for execution in executions)
        assert next(item for item in executions if item.agent_name == "Geographical Filtering Agent").status == "failed"


def test_geography_is_persisted_running_before_enrichment(database, monkeypatch):
    client, session_factory = database
    configured = replace(orchestration.settings, feeds=("good",))
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/geo-start")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [],
    })

    def observe_geography_start(article, item):
        with session_factory() as observer:
            run = observer.query(CollectionRun).order_by(CollectionRun.id.desc()).first()
            execution = observer.query(AgentExecution).filter_by(
                run_id=run.id,
                agent_name="Geographical Filtering Agent",
            ).one()
            assert execution.status == "running"
            assert execution.completed_at is None
            assert execution.last_heartbeat_at is not None
            assert run.last_heartbeat_at is not None

    monkeypatch.setattr(orchestration, "apply_location_enrichment", observe_geography_start)

    response = client.post("/api/collection/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_successful_orchestration_records_terminal_counts_and_completion(database, monkeypatch):
    client, _ = database
    configured = replace(orchestration.settings, feeds=("good",))
    monkeypatch.setattr(orchestration, "settings", configured)
    monkeypatch.setattr(main, "settings", configured)
    monkeypatch.setattr(orchestration, "collect_feeds", lambda feeds: {
        "articles": [article_data("https://example.com/completion")],
        "successful": [{"feed_url": "good", "source_name": "Good", "status": "success", "article_count": 1}],
        "failed": [],
    })

    response = client.post("/api/collection/run")

    assert response.json()["status"] == "completed"
    history = client.get("/api/collection/history").json()
    assert history[0]["id"] == response.json()["run_id"]
    assert history[0]["completed_at"] is not None
    assert history[0]["inserted"] == 1


def test_agent_status_recovers_stale_run_before_reporting(database):
    client, session_factory = database
    now = datetime.now(timezone.utc)
    stale_time = now - orchestration.STALE_RUN_AFTER - timedelta(minutes=1)
    with session_factory() as db:
        run = CollectionRun(
            status="running",
            started_at=stale_time,
            last_heartbeat_at=stale_time,
        )
        db.add(run)
        db.flush()
        db.add(AgentExecution(
            agent_name="Orchestration Agent",
            status="running",
            run_id=run.id,
            started_at=stale_time,
            last_heartbeat_at=stale_time,
        ))
        db.add(CollectionLock(id=1, run_id=run.id, acquired_at=stale_time, heartbeat_at=stale_time))
        db.commit()
        stale_run_id = run.id

    response = client.get("/api/agents/status")
    assert response.status_code == 200
    orchestration_status = next(
        item for item in response.json() if item["name"] == "Orchestration Agent"
    )
    assert orchestration_status["status"] == "failed"
    assert orchestration_status["run_id"] == stale_run_id
    assert orchestration_status["completed_at"] is not None
    assert orchestration_status["last_heartbeat_at"] is not None

    with session_factory() as db:
        assert db.get(CollectionLock, 1).run_id is None


def test_stale_run_recovery_marks_only_abandoned_run_terminal(database):
    _, session_factory = database
    now = datetime.now(timezone.utc)
    stale_time = now - orchestration.STALE_RUN_AFTER - timedelta(minutes=1)
    with session_factory() as db:
        run = CollectionRun(
            status="running",
            started_at=stale_time,
            last_heartbeat_at=stale_time,
            inserted=3,
        )
        db.add(run)
        db.flush()
        execution = AgentExecution(
            agent_name="Orchestration Agent",
            status="running",
            run_id=run.id,
            started_at=stale_time,
            last_heartbeat_at=stale_time,
            processed_count=3,
        )
        db.add(execution)
        db.add(CollectionLock(id=1, run_id=run.id, acquired_at=stale_time, heartbeat_at=stale_time))
        db.commit()

        assert orchestration.recover_stale_runs(db, now) == 1
        db.refresh(run)
        db.refresh(execution)
        assert run.status == "failed"
        assert run.completed_at is not None
        assert run.inserted == 3
        assert execution.status == "failed"
        assert execution.completed_at is not None
        assert db.get(CollectionLock, 1).run_id is None
