import re

CATEGORY_RULES = {
    "Politics": ("election", "parliament", "president", "minister", "government", "policy", "vote", "senate", "congress", "democracy"),
    "Business": ("business", "market", "stock", "economy", "company", "finance", "earnings", "revenue", "trade", "bank", "investment", "inflation"),
    "Technology": ("technology", "software", "artificial intelligence", " ai ", "cyber", "startup", "computer", "chip", "smartphone", "app", "robot"),
    "Sports": ("sports", "football", "cricket", "basketball", "tennis", "match", "tournament", "athlete", "league", "olympic", "championship"),
    "Health": ("health", "hospital", "medical", "vaccine", "disease", "doctor", "medicine", "cancer", "mental health", "public health"),
    "Education": ("education", "school", "university", "student", "exam", "college", "classroom", "curriculum", "scholarship"),
    "Entertainment": ("movie", "music", "actor", "film", "celebrity", "entertainment", "television", "streaming", "concert", "festival", "box office"),
    "Science": ("science", "research", "space", " nasa ", "laboratory", "discovery", "astronomy", "physics", "biology", "climate study"),
    "Environment": ("climate", "environment", "pollution", "wildlife", "carbon", "weather", "conservation", "renewable", "emissions"),
    "World": ("international", "world", "global", "united nations", "foreign", "diplomacy", "conflict", "war", "earthquake"),
}


def classify_article(title: str, summary: str | None = None) -> tuple[str, str]:
    text = f" {re.sub(r'[^a-z0-9]+', ' ', f'{title} {summary or ""}'.lower())} "
    for category, keywords in CATEGORY_RULES.items():
        matched = next((keyword.strip() for keyword in keywords if f" {keyword.strip()} " in text), None)
        if matched:
            return category, f"Matched keyword: {matched}"
    return "Other", "No configured category keyword matched"
