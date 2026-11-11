
import re

CATEGORY_RULES = {
    "Politics": ("election", "parliament", "president", "minister", "government", "policy", "vote", "senate", "congress", "democracy"),
    "Business": ("business", "market", "stock", "economy", "company", "finance", "earnings", "revenue", "trade", "bank", "investment", "inflation"),
    "Technology": ("technology", "software", "artificial intelligence", " ai ", "cyber", "startup", "computer", "chip", "smartphone", "robot"),
    "Sports": ("sports", "football", "cricket", "basketball", "tennis", "match", "tournament", "athlete", "league", "olympic", "championship"),
    "Health": ("health", "hospital", "medical", "vaccine", "disease", "doctor", "medicine", "cancer", "mental health", "public health"),
    "Education": ("education", "school", "university", "student", "exam", "college", "classroom", "curriculum", "scholarship"),
    "Entertainment": ("movie", "music", "actor", "film", "celebrity", "entertainment", "television", "streaming", "concert", "festival", "box office"),
    "Science": ("science", "research", "space", "nasa", "laboratory", "discovery", "astronomy", "physics", "biology", "climate study"),
    "Environment": ("climate", "environment", "pollution", "wildlife", "carbon", "weather", "conservation", "renewable", "emissions"),
    "World": ("international", "world", "global", "united nations", "foreign", "diplomacy", "conflict", "war", "earthquake"),
}


def _match_category(text: str) -> tuple[str | None, str | None]:
    for category, keywords in CATEGORY_RULES.items():
        matched = next(
            (
                keyword.strip()
                for keyword in keywords
                if f" {keyword.strip()} " in text
            ),
            None,
        )
        if matched:
            return category, matched

    return None, None


def _normalize_text(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return f" {normalized.strip()} "


def classify_article(title: str, summary: str | None = None) -> tuple[str, str]:
    # Prefer the headline because it usually describes the main subject.
    category, matched = _match_category(_normalize_text(title))

    if category:
        return category, f"Matched title keyword: {matched}"

    # Use the summary only when the title has no matching category.
    category, matched = _match_category(_normalize_text(summary))

    if category:
        return category, f"Matched summary keyword: {matched}"

    return "Other", "No configured category keyword matched"
