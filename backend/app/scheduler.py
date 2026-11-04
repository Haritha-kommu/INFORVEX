import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .agents.orchestration import (
    claim_database_lock,
    recover_stale_runs,
    release_database_lock,
    run_collection,
)
from .config import settings
from .database import SessionLocal
from .models import Article, ArticleAnalytics

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def scheduled_collection() -> None:
    """Run scheduled news collection."""
    db = SessionLocal()

    try:
        run = run_collection(db)

        logger.info(
            "Scheduled collection completed: status=%s inserted=%s",
            run.status,
            run.inserted,
        )

    except Exception:
        logger.exception("Scheduled collection failed")

    finally:
        db.close()


def cleanup_old_news() -> dict:
    """Delete old articles and their associated analytics records."""
    retention_days = settings.retention_days

    if retention_days <= 0:
        logger.info(
            "News retention cleanup skipped: RETENTION_DAYS is not enabled"
        )

        return {
            "status": "skipped",
            "reason": "RETENTION_DAYS is not enabled",
            "deleted_articles": 0,
            "deleted_analytics": 0,
        }

    db = SessionLocal()
    owner_id = -time.time_ns()
    lock_acquired = False

    try:
        recover_stale_runs(db)
        claim_database_lock(db, owner_id)
        lock_acquired = True

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=retention_days
        )

        old_article_ids = (
            db.query(Article.id)
            .filter(Article.first_fetched_at < cutoff)
            .subquery()
        )

        deleted_analytics = (
            db.query(ArticleAnalytics)
            .filter(
                ArticleAnalytics.article_id.in_(old_article_ids)
            )
            .delete(synchronize_session=False)
        )

        deleted_articles = (
            db.query(Article)
            .filter(Article.first_fetched_at < cutoff)
            .delete(synchronize_session=False)
        )

        db.commit()

        logger.info(
            "News retention cleanup completed: "
            "deleted_articles=%s deleted_analytics=%s "
            "retention_days=%s",
            deleted_articles,
            deleted_analytics,
            retention_days,
        )

        return {
            "status": "completed",
            "deleted_articles": deleted_articles,
            "deleted_analytics": deleted_analytics,
            "retention_days": retention_days,
        }

    except Exception as exc:
        db.rollback()
        logger.exception("News retention cleanup failed")

        raise RuntimeError(
            "News retention cleanup failed"
        ) from exc

    finally:
        if lock_acquired:
            try:
                release_database_lock(db, owner_id)

            except Exception:
                db.rollback()
                logger.exception(
                    "News retention cleanup lock release failed"
                )

        db.close()


def start_scheduler() -> None:
    """Start internal scheduled jobs only when enabled in configuration."""
    if not settings.scheduler_enabled:
        logger.info(
            "Internal scheduler is disabled. "
            "External scheduling can be used instead."
        )
        return

    if scheduler.running:
        logger.info("Internal scheduler is already running.")
        return

    scheduler.add_job(
        scheduled_collection,
        "interval",
        minutes=settings.collection_interval_minutes,
        id="newsphere-collection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        cleanup_old_news,
        trigger="interval",
        hours=24,
        id="cleanup_old_news",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()

    logger.info("Internal scheduler started successfully.")


def stop_scheduler() -> None:
    """Stop the internal scheduler safely."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Internal scheduler stopped.")