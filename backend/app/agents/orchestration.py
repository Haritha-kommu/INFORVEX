
from datetime import datetime, timedelta, timezone
import logging
from threading import Lock

from sqlalchemy import or_, text, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AgentExecution, CollectionLock, CollectionRun, FeedExecution
from .database_management import store_article
from .geographical_filtering import apply_location_enrichment
from .news_segregation import classify_article
from .news_analytics import analyze_articles
from .web_news_scraping import collect_feeds


collection_lock = Lock()
logger = logging.getLogger(__name__)
STALE_RUN_AFTER = timedelta(minutes=30)


BASE_AGENT_NAMES = (
    "Orchestration Agent",
    "Web News Scraping Agent",
    "Database Management Agent",
    "News Segregation Agent",
    "Geographical Filtering Agent",
)

# Keep this internal name for database and test compatibility.
# The dashboard can display it as "NLP Agent".
ANALYTICS_AGENT_NAME = "News Analytics Agent"
ALL_AGENT_NAMES = BASE_AGENT_NAMES + (ANALYTICS_AGENT_NAME,)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finish(
    execution: AgentExecution,
    status: str,
    count: int = 0,
    error: str | None = None,
) -> None:
    execution.status = status
    execution.processed_count = count
    execution.error = error
    execution.completed_at = _now()
    execution.last_heartbeat_at = execution.completed_at


def _touch(
    db: Session,
    run: CollectionRun,
    *executions: AgentExecution,
) -> None:
    heartbeat = _now()
    run.last_heartbeat_at = heartbeat

    for execution in executions:
        execution.last_heartbeat_at = heartbeat

    db.execute(
        update(CollectionLock)
        .where(
            CollectionLock.id == 1,
            CollectionLock.run_id == run.id,
        )
        .values(heartbeat_at=heartbeat)
    )


def recover_stale_runs(
    db: Session,
    now: datetime | None = None,
) -> int:
    now = now or _now()
    cutoff = now - STALE_RUN_AFTER

    stale_runs = (
        db.query(CollectionRun)
        .filter(
            CollectionRun.status == "running",
            or_(
                CollectionRun.last_heartbeat_at < cutoff,
                CollectionRun.last_heartbeat_at.is_(None)
                & (CollectionRun.started_at < cutoff),
            ),
        )
        .all()
    )

    for run in stale_runs:
        run.status = "failed"
        run.completed_at = now
        run.last_heartbeat_at = now
        run.error = (
            (run.error + "; ") if run.error else ""
        ) + "Collection interrupted before completion"

        db.execute(
            update(CollectionLock)
            .where(
                CollectionLock.id == 1,
                CollectionLock.run_id == run.id,
            )
            .values(
                run_id=None,
                acquired_at=None,
                heartbeat_at=None,
            )
        )

        executions = (
            db.query(AgentExecution)
            .filter(
                or_(
                    AgentExecution.run_id == run.id,
                    (
                        AgentExecution.run_id.is_(None)
                        & (AgentExecution.started_at >= run.started_at)
                    ),
                ),
                AgentExecution.status.in_(("pending", "running")),
            )
            .all()
        )

        for execution in executions:
            status = (
                "failed"
                if execution.status == "running"
                else "skipped"
            )
            _finish(
                execution,
                status,
                execution.processed_count,
                "Collection interrupted before completion",
            )

    if stale_runs:
        db.commit()

    return len(stale_runs)


def claim_database_lock(db: Session, owner_id: int) -> None:
    now = _now()
    cutoff = now - STALE_RUN_AFTER

    dialect = db.get_bind().dialect.name

    if dialect == "postgresql":
        insert_sql = (
            "INSERT INTO collection_lock "
            "(id, run_id, acquired_at, heartbeat_at) "
            "VALUES (1, NULL, NULL, NULL) "
            "ON CONFLICT (id) DO NOTHING"
        )
    else:
        insert_sql = (
            "INSERT OR IGNORE INTO collection_lock "
            "(id, run_id, acquired_at, heartbeat_at) "
            "VALUES (1, NULL, NULL, NULL)"
        )

    db.execute(text(insert_sql))

    claimed = db.execute(
        update(CollectionLock)
        .where(CollectionLock.id == 1)
        .where(
            or_(
                CollectionLock.run_id.is_(None),
                CollectionLock.heartbeat_at < cutoff,
                CollectionLock.heartbeat_at.is_(None),
            )
        )
        .values(
            run_id=owner_id,
            acquired_at=now,
            heartbeat_at=now,
        )
    )

    if claimed.rowcount != 1:
        raise RuntimeError("A collection run is already in progress")


def release_database_lock(db: Session, owner_id: int) -> None:
    db.execute(
        update(CollectionLock)
        .where(
            CollectionLock.id == 1,
            CollectionLock.run_id == owner_id,
        )
        .values(
            run_id=None,
            acquired_at=None,
            heartbeat_at=None,
        )
    )
    db.commit()


def run_collection(db: Session) -> CollectionRun:
    if not collection_lock.acquire(blocking=False):
        raise RuntimeError("A collection run is already in progress")

    run = None
    run_id = None
    execution_ids = {}

    try:
        recover_stale_runs(db)

        run = CollectionRun(
            status="running",
            last_heartbeat_at=_now(),
        )
        db.add(run)
        db.flush()

        run_id = run.id
        claim_database_lock(db, run.id)

        agent_names = BASE_AGENT_NAMES + (
            (ANALYTICS_AGENT_NAME,)
            if settings.analytics_enabled
            else ()
        )

        executions = {
            name: AgentExecution(
                agent_name=name,
                status="pending",
                run_id=run.id,
            )
            for name in agent_names
        }

        db.add_all(executions.values())

        executions["Orchestration Agent"].status = "running"
        _touch(db, run, executions["Orchestration Agent"])
        db.commit()

        execution_ids = {
            name: execution.id
            for name, execution in executions.items()
        }
        run_id = run.id

        # 1. Web News Scraping Agent
        scraping = executions["Web News Scraping Agent"]
        scraping.status = "running"
        _touch(db, run, scraping)
        db.commit()

        result = collect_feeds(settings.feeds)

        run.retrieved = len(result["articles"])
        run.failed = len(result["failed"])

        for feed_result in result["successful"]:
            if isinstance(feed_result, str):
                feed_result = {
                    "feed_url": feed_result,
                    "source_name": feed_result,
                    "status": "success",
                    "article_count": 0,
                }

            db.add(
                FeedExecution(
                    feed_url=feed_result["feed_url"],
                    source_name=feed_result["source_name"],
                    status=feed_result["status"],
                    article_count=feed_result["article_count"],
                )
            )

        for feed_error in result["failed"]:
            db.add(
                FeedExecution(
                    feed_url=feed_error["feed"],
                    source_name=feed_error.get(
                        "source_name",
                        feed_error["feed"],
                    ),
                    status="failed",
                    error=feed_error["error"],
                )
            )

        db.commit()

        if not settings.feeds:
            message = result.get(
                "message",
                "No feeds configured",
            )

            _finish(scraping, "failed", error=message)

            for name in agent_names[2:]:
                _finish(
                    executions[name],
                    "skipped",
                    error="Not run because no feeds were configured",
                )

            run.status = "failed"
            run.error = message
            run.completed_at = _now()

            _finish(
                executions["Orchestration Agent"],
                "failed",
                error=message,
            )

            _touch(db, run)
            db.commit()
            return run

        _finish(
            scraping,
            "partial" if result["failed"] else "completed",
            len(result["articles"]),
            "; ".join(
                f"{item['feed']}: {item['error']}"
                for item in result["failed"]
            ) or None,
        )
        db.commit()

        # 2. Database Management Agent
        persistence = executions["Database Management Agent"]
        persistence.status = "running"
        _touch(db, run, persistence)
        db.commit()

        inserted_pairs = []
        feed_counts = {}

        for item in result["articles"]:
            outcome, article = store_article(db, item)
            feed_url = item.get("feed_url", item["source_name"])

            counts = feed_counts.setdefault(
                feed_url,
                {"inserted": 0, "duplicates": 0},
            )

            if outcome == "inserted":
                run.inserted += 1
                inserted_pairs.append((article, item))
                counts["inserted"] += 1
            else:
                run.duplicates += 1
                counts["duplicates"] += 1

        for feed_url, counts in feed_counts.items():
            execution = (
                db.query(FeedExecution)
                .filter(FeedExecution.feed_url == feed_url)
                .order_by(FeedExecution.checked_at.desc())
                .first()
            )

            if execution:
                execution.inserted_count = counts["inserted"]
                execution.duplicate_count = counts["duplicates"]

        inserted_articles = [
            article for article, _ in inserted_pairs
        ]

        _finish(
            persistence,
            "completed",
            len(result["articles"]),
        )
        db.commit()

        # 3. News Segregation Agent
        segregation = executions["News Segregation Agent"]
        segregation.status = "running"
        _touch(db, run, segregation)

        for article in inserted_articles:
            (
                article.category,
                article.category_explanation,
            ) = classify_article(article.title, article.summary)

        _finish(
            segregation,
            "completed",
            len(inserted_articles),
        )
        db.commit()

        # 4. Geographical Filtering Agent
        geography = executions["Geographical Filtering Agent"]
        geography.status = "running"
        _touch(db, run, geography)
        db.commit()

        processed_geography = 0

        try:
            for article, item in inserted_pairs:
                apply_location_enrichment(article, item)
                processed_geography += 1
                geography.processed_count = processed_geography
                _touch(db, run, geography)
                db.commit()

        except Exception as exc:
            _finish(
                geography,
                "failed",
                processed_geography,
                str(exc),
            )
            db.commit()

            raise RuntimeError(
                f"Geographical Filtering Agent failed: {exc}"
            ) from exc

        _finish(
            geography,
            "completed",
            len(inserted_articles),
        )

        # 5. NLP Agent (stored internally as News Analytics Agent)
        nlp_error = None

        if settings.analytics_enabled:
            nlp = executions[ANALYTICS_AGENT_NAME]
            nlp.status = "running"
            _touch(db, run, nlp)
            db.commit()

            try:
                # Analyze only newly inserted articles.
                processed = analyze_articles(
                    db,
                    [article.id for article in inserted_articles],
                )

                _finish(nlp, "completed", processed)

            except Exception as exc:
                logger.exception("News Analytics Agent failed")
                nlp_error = f"News Analytics Agent: {exc}"
                _finish(nlp, "failed", error=str(exc))

            db.commit()

        # Complete orchestration
        collection_errors = [
            f"{item['feed']}: {item['error']}"
            for item in result["failed"]
        ]

        if nlp_error:
            collection_errors.append(nlp_error)

        run.status = (
            "completed_with_errors"
            if result["failed"]
            else "completed_with_warnings"
            if nlp_error
            else "completed"
        )

        run.error = "; ".join(collection_errors) or None
        run.completed_at = _now()

        _finish(
            executions["Orchestration Agent"],
            run.status,
            run.inserted,
            run.error,
        )

        _touch(db, run)
        db.commit()

        return run

    except Exception as exc:
        db.rollback()

        persisted_run = (
            db.get(CollectionRun, run_id)
            if run_id is not None
            else None
        )

        if persisted_run:
            persisted_run.status = "failed"
            persisted_run.error = str(exc)
            persisted_run.completed_at = _now()
            persisted_run.last_heartbeat_at = persisted_run.completed_at

        for name, execution_id in execution_ids.items():
            persisted_execution = db.get(
                AgentExecution,
                execution_id,
            )

            if (
                persisted_execution
                and persisted_execution.status in {"pending", "running"}
            ):
                status = (
                    "failed"
                    if (
                        persisted_execution.status == "running"
                        or name == "Orchestration Agent"
                    )
                    else "skipped"
                )

                _finish(
                    persisted_execution,
                    status,
                    error=str(exc),
                )

        if persisted_run:
            db.commit()
            return persisted_run

        raise

    finally:
        if run_id is not None:
            try:
                release_database_lock(db, run_id)
            except Exception:
                db.rollback()

        collection_lock.release()
