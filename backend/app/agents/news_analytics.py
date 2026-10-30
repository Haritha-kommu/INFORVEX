
import html
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Article, ArticleAnalytics

logger = logging.getLogger(__name__)

HTML_TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[a-z][a-z'-]{2,}", re.IGNORECASE)

# Remove common HTML remnants and URL-related fragments.
HTML_NOISE_RE = re.compile(
    r"\b(?:href|src|https|http|www)\b",
    re.IGNORECASE,
)


def _dependencies():
    try:
        from sklearn.feature_extraction.text import (
            ENGLISH_STOP_WORDS,
            TfidfVectorizer,
        )
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        import spacy
    except ImportError as exc:
        raise RuntimeError(
            "News Analytics Agent dependencies are unavailable. "
            "Install backend requirements."
        ) from exc

    return ENGLISH_STOP_WORDS, TfidfVectorizer, SentimentIntensityAnalyzer, spacy


def _repair_text_encoding(text: str) -> str:
    """
    Repair common UTF-8 text incorrectly decoded using Latin-1 or CP1252.
    """
    markers = ("Ã", "Â", "â", "ð", "\ufffd")

    if not any(marker in text for marker in markers):
        return text

    for encoding in ("cp1252", "latin-1"):
        try:
            repaired = text.encode(encoding).decode("utf-8")

            if "\ufffd" not in repaired:
                return repaired

        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

    return text


def _clean_text(text: str | None) -> str:
    """
    Clean article text for analytics without modifying the stored article.
    """
    if not text:
        return ""

    # Decode HTML entities such as &amp; and &nbsp;.
    text = html.unescape(text)

    # Repair common character-encoding errors.
    text = _repair_text_encoding(text)

    # Remove HTML tags and URLs.
    text = HTML_TAG_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)

    # Remove leftover HTML attribute words.
    text = HTML_NOISE_RE.sub(" ", text)

    # Normalize whitespace.
    text = SPACE_RE.sub(" ", text)

    return text.strip()


def _article_text(article: Article) -> str:
    parts = (
        _clean_text(article.title),
        _clean_text(article.summary),
        _clean_text(article.content),
    )

    return " ".join(part for part in parts if part)


def _clean_words(text: str, stop_words: set[str]) -> list[str]:
    words = WORD_RE.findall(text.casefold())

    return [
        word
        for word in words
        if word not in stop_words and len(word) > 2
    ]


def _extract_keywords(
    text: str,
    words: list[str],
    tfidf_vectorizer,
) -> list[dict]:
    """
    Extract important single-word and two-word keywords using TF-IDF.
    """
    if not words:
        return []

    vectorizer = tfidf_vectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=12,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z'-]{2,}\b",
    )

    try:
        matrix = vectorizer.fit_transform([text])
        scores = matrix.toarray()[0]

        ranked = sorted(
            zip(vectorizer.get_feature_names_out(), scores),
            key=lambda item: item[1],
            reverse=True,
        )

        counts = Counter(words)

        return [
            {
                "term": term,
                "score": round(float(score), 5),
                "frequency": counts.get(term.split()[0], 0),
            }
            for term, score in ranked[:10]
        ]

    except ValueError:
        return [
            {
                "term": term,
                "score": 0.0,
                "frequency": count,
            }
            for term, count in Counter(words).most_common(10)
        ]


def _extract_entities(text: str, nlp) -> list[dict]:
    """
    Extract people, organizations and geographical entities.
    """
    if not nlp or not text:
        return []

    entities = []
    seen = set()

    for entity in nlp(text).ents:
        if entity.label_ not in {"PERSON", "ORG", "GPE", "LOC"}:
            continue

        name = _repair_text_encoding(entity.text)
        name = SPACE_RE.sub(" ", name).strip(" ,.-")

        key = (name.casefold(), entity.label_)

        if len(name) < 2 or key in seen:
            continue

        seen.add(key)

        entities.append(
            {
                "text": name,
                "label": entity.label_,
            }
        )

    return entities


def analyze_articles(
    db: Session,
    article_ids: list[int] | None = None,
    force: bool = False,
) -> int:
    """
    Analyze articles using sentiment analysis, TF-IDF and spaCy.

    When force=False, existing analytics records are skipped.
    When force=True, existing analytics records are refreshed.

    Original Article records are never modified by this function.
    """

    stop_words, tfidf_vectorizer, sentiment_analyzer, spacy = _dependencies()

    analyzer = sentiment_analyzer()

    try:
        nlp = spacy.load(settings.spacy_model)

    except (OSError, IOError) as exc:
        raise RuntimeError(
            f"News Analytics Agent spaCy model '{settings.spacy_model}' "
            "is unavailable. Install the configured model."
        ) from exc

    query = db.query(Article)

    if article_ids:
        query = query.filter(Article.id.in_(article_ids))

    articles = query.order_by(Article.id).all()

    analyzed = 0
    stop_word_set = set(stop_words)

    for article in articles:
        existing = (
            db.query(ArticleAnalytics)
            .filter_by(article_id=article.id)
            .first()
        )

        if existing and not force:
            continue

        # Clean text before passing it to analytics models.
        text = _article_text(article)

        # Sentiment analysis.
        sentiment = analyzer.polarity_scores(text)
        compound = float(sentiment["compound"])

        if compound >= 0.05:
            label = "positive"
        elif compound <= -0.05:
            label = "negative"
        else:
            label = "neutral"

        # Keyword extraction.
        words = _clean_words(text, stop_word_set)

        keywords = _extract_keywords(
            text,
            words,
            tfidf_vectorizer,
        )

        # Named entity extraction.
        entities = _extract_entities(text, nlp)

        payload = {
            "sentiment": label,
            "sentiment_score": compound,
            "keywords_json": json.dumps(
                keywords,
                ensure_ascii=False,
            ),
            "entities_json": json.dumps(
                entities,
                ensure_ascii=False,
            ),
            "analyzed_at": datetime.now(timezone.utc),
            "analyzer_version": (
                f"v3-encoding-cleaned-vader-tfidf-spacy:{settings.spacy_model}"
            ),
        }

        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
        else:
            db.add(
                ArticleAnalytics(
                    article_id=article.id,
                    **payload,
                )
            )

        analyzed += 1

    db.commit()

    logger.info(
        "News Analytics Agent completed: %s articles analyzed",
        analyzed,
    )

    return analyzed
