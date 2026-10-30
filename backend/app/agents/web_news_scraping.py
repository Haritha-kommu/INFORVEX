from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
import logging

from .geographical_filtering import enrich_location

logger = logging.getLogger(__name__)

def _published(entry) -> datetime | None:
    for parsed_key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(parsed_key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    for value_key in ("published", "updated"):
        value = entry.get(value_key)
        if value:
            try:
                parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
            try:
                parsed = parsedate_to_datetime(str(value))
                return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def collect_feeds(feed_urls: tuple[str, ...], timeout_seconds: float = 10.0) -> dict:
    articles: list[dict] = []
    successful: list[str] = []
    failed: list[dict] = []
    if not feed_urls:
        return {"articles": [], "successful": [], "failed": [], "message": "No feeds configured"}
    for feed_url in feed_urls:
        try:
            response = httpx.get(
                feed_url,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=True,
                headers={"User-Agent": "NewsSphere/1.0 RSS reader"},
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(str(parsed.bozo_exception))
            source = parsed.feed.get("title", "").strip() or feed_url
            successful.append(feed_url)
            feed_articles = []
            for entry in parsed.entries:
                url = entry.get("link")
                title = entry.get("title")
                if not url or not title:
                    continue
                article = {
                    "feed_url": feed_url,
                    "title": title.strip(),
                    "canonical_url": url,
                    "source_name": source,
                    "summary": entry.get("summary") or None,
                    "publication_time": _published(entry),
                }
                article.update(enrich_location({
                    **entry,
                    "title": article["title"],
                    "summary": article["summary"],
                    "location": entry.get("location"),
                }))
                feed_articles.append(article)
            articles.extend(feed_articles)
            result = {
                "feed_url": feed_url,
                "source_name": source,
                "status": "success",
                "article_count": len(feed_articles),
            }
            successful[-1] = result
        except Exception as exc:
            logger.warning("Feed collection failed for %s: %s", feed_url, exc)
            failed.append({"feed": feed_url, "error": str(exc)})
    return {"articles": articles, "successful": successful, "failed": failed}
