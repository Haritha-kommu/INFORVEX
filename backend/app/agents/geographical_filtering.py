import re

from ..geo_reference import GEOGRAPHY, resolve_location

UNKNOWN_VALUES = {"unknown", "n/a", "na", "none", ""}


def normalize_location(value: str | None) -> str | None:
    return " ".join(value.split()).casefold() if value else None


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase.casefold())}\b", text.casefold()) is not None


STRUCTURED_LOCATION_KEYS = (
    "event_location", "event_place", "location", "geo", "spatial",
    "dcterms_spatial", "dc:coverage", "place", "places",
)


def _structured_location(entry: dict) -> dict:
    """Extract only source-supplied location fields, never feed-level metadata."""
    candidates = [entry]
    for key in STRUCTURED_LOCATION_KEYS:
        value = entry.get(key)
        if isinstance(value, dict):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    values = {}
    for candidate in candidates:
        for field, keys in {
            "country": ("country", "country_name"),
            "state": ("state", "province", "region", "state_name"),
            "district": ("district", "county", "city", "municipality", "district_name"),
        }.items():
            if field in values:
                continue
            for key in keys:
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    values[field] = " ".join(value.split())
                    break
    return values


_CONTEXT_CUES = (
    "in", "at", "near", "from", "within", "across", "outside",
    "inside", "around", "following", "enters", "enter", "entered",
    "entering", "reaches", "reach", "hit", "hits", "strikes", "struck",
    "affects", "affected", "affecting", "inundates", "inundated", "toward",
    "towards", "reported in", "reported at",
)


def _build_location_alias_index() -> dict[str, list[tuple]]:
    """Index all canonical names and aliases once, instead of compiling a regex
    separately for every place in every article.
    """
    index: dict[str, list[tuple]] = {}

    def add(alias: str, candidate: tuple) -> None:
        key = " ".join(alias.split()).casefold()
        if key:
            index.setdefault(key, []).append(candidate)

    for country, data in GEOGRAPHY.items():
        for alias in (country, *data.get("aliases", [])):
            add(alias, ("country", country))
        for state, state_data in data["states"].items():
            state_aliases = state_data.get("aliases", []) if isinstance(state_data, dict) else []
            for alias in (state, *state_aliases):
                add(alias, ("state", country, state))
            districts = state_data.get("districts", []) if isinstance(state_data, dict) else state_data
            for district in districts:
                district_name = district.get("name") if isinstance(district, dict) else district
                aliases = district.get("aliases", []) if isinstance(district, dict) else []
                if district_name:
                    for alias in (district_name, *aliases):
                        add(alias, ("district", country, state, district_name))
    return index


_LOCATION_ALIAS_INDEX = _build_location_alias_index()
# Longest-first prevents a shorter place name from winning when it is a prefix
# of a longer name (for example, "Bengaluru" vs. "Bengaluru Urban").
_LOCATION_ALIASES = sorted(_LOCATION_ALIAS_INDEX, key=len, reverse=True)
_LOCATION_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(cue) for cue in _CONTEXT_CUES) + r")\s+(?P<place>"
    + "|".join(re.escape(alias) for alias in _LOCATION_ALIASES)
    + r")\b",
    re.IGNORECASE,
) if _LOCATION_ALIASES else None


def enrich_location(entry: dict) -> dict:
    """Return only explicit or unambiguous reference matches.

    The title/summary rule is deliberately conservative: a state or district
    can only be inferred when its country hierarchy is uniquely identified.
    """
    explicit = _structured_location(entry)
    if explicit:
        resolved = resolve_location(explicit.get("country"), explicit.get("state"), explicit.get("district"))
        if resolved:
            return {
                **resolved,
                "location_provenance": "source",
                "location_confidence": "high",
                "location_resolution_reason": "structured event-location metadata",
            }
        return {
            "location_provenance": "unknown",
            "location_confidence": None,
            "location_resolution_reason": "structured location was incomplete or outside the reference",
        }

    text = f"{entry.get('title', '')} {entry.get('summary') or ''}"
    country_candidates = set()
    state_candidates = set()
    district_candidates = set()
    # One precompiled combined regex scans the text once. The prior approach
    # repeatedly compiled/searched one pattern for every country, state and
    # district for every article, making collection extremely slow.
    if _LOCATION_PATTERN is not None:
        for match in _LOCATION_PATTERN.finditer(text):
            alias = " ".join(match.group("place").split()).casefold()
            for candidate in _LOCATION_ALIAS_INDEX.get(alias, ()):
                if candidate[0] == "country":
                    country_candidates.add(candidate[1])
                elif candidate[0] == "state":
                    state_candidates.add((candidate[1], candidate[2]))
                elif candidate[0] == "district":
                    district_candidates.add((candidate[1], candidate[2], candidate[3]))
    if len(district_candidates) == 1:
        country, state, district = next(iter(district_candidates))
        resolved = {"country": country, "state": state, "district": district}
    elif len(state_candidates) == 1:
        country, state = next(iter(state_candidates))
        resolved = {"country": country, "state": state}
    elif len(country_candidates) == 1:
        resolved = {"country": next(iter(country_candidates))}
    else:
        resolved = None
    if resolved:
        return {
            **resolved,
            "location_provenance": "context_reference",
            "location_confidence": "medium",
            "location_resolution_reason": "unique reference place used with an event-context cue",
        }
    return {
        "location_provenance": "unknown",
        "location_confidence": None,
        "location_resolution_reason": "no unique event location; mentioned places are not sufficient",
    }


def normalize_article_locations(article) -> None:
    for field in ("country", "state", "district"):
        value = getattr(article, field)
        if value:
            setattr(article, field, " ".join(value.split()))


def apply_location_enrichment(article, entry: dict) -> dict:
    result = enrich_location(entry)
    for field in ("country", "state", "district", "location_provenance", "location_confidence"):
        if field in result and field != "location_resolution_reason" and (field != "location_provenance" or result[field] != "unknown"):
            setattr(article, field, result[field])
    normalize_article_locations(article)
    return result


def matches_location(article, country=None, state=None, district=None) -> bool:
    requested = (country, state, district)
    actual = (article.country, article.state, article.district)
    return all(
        wanted is None or normalize_location(wanted) == normalize_location(got)
        for wanted, got in zip(requested, actual)
    )


def has_valid_location(article) -> bool:
    normalized_country = normalize_location(article.country)
    if not normalized_country or normalized_country in UNKNOWN_VALUES:
        return False
    for value in (article.state, article.district):
        if normalize_location(value) in UNKNOWN_VALUES:
            return False
    country_name = next((name for name in GEOGRAPHY if normalize_location(name) == normalized_country), None)
    if not country_name:
        return False
    return bool(resolve_location(article.country, article.state, article.district))
