import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Article
from .news_segregation import classify_article


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = re.sub(r"/+$", "", parts.path) or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def store_article(db: Session, article_data: dict) -> tuple[str, Article | None]:
    canonical_url = normalize_url(article_data["canonical_url"])
    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    if db.query(Article).filter_by(url_hash=url_hash).first():
        return "duplicate", None
    category, explanation = classify_article(article_data["title"], article_data.get("summary"))
    article = Article(
        **{key: value for key, value in article_data.items() if key in {
            "title", "source_name", "summary", "content", "country", "state",
            "district", "location_provenance", "location_confidence", "publication_time"
        }},
        canonical_url=canonical_url,
        url_hash=url_hash,
        category=category,
        category_explanation=explanation,
    )
    try:
        with db.begin_nested():
            db.add(article)
            db.flush()
    except IntegrityError:
        return "duplicate", None
    return "inserted", article
