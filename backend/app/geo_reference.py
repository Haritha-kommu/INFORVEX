"""Load the maintained geography reference without inventing article metadata.

Country coverage follows ISO 3166-1. Administrative coverage is intentionally
partial and limited to the relationships present in the local reference.
"""

import json
from pathlib import Path

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "geography.json"
REFERENCE = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
GEOGRAPHY = REFERENCE["countries"]


def _aliases(value: str, data: dict) -> tuple[str, ...]:
    return (value, *data.get("aliases", [])) if isinstance(data, dict) else (value,)


def canonical_name(values: dict, value: str | None) -> str | None:
    if not value:
        return None
    normalized = " ".join(value.split()).casefold()
    for name, data in values.items():
        if any(normalized == " ".join(alias.split()).casefold() for alias in _aliases(name, data)):
            return name
    return None


def resolve_location(country: str | None, state: str | None = None, district: str | None = None) -> dict:
    """Resolve reference names without treating the reference as article evidence."""
    country_name = canonical_name(GEOGRAPHY, country)
    if not country_name:
        return {}
    states = GEOGRAPHY[country_name]["states"]
    state_name = canonical_name(states, state) if state else None
    if state and not state_name:
        return {}
    if not district:
        return {"country": country_name, **({"state": state_name} if state_name else {})}
    if state_name:
        district_values = states[state_name].get("districts", []) if isinstance(states[state_name], dict) else states[state_name]
        district_name = next(
            (item.get("name") if isinstance(item, dict) else item
             for item in district_values
             if any(
                 " ".join(district.split()).casefold() == " ".join(alias.split()).casefold()
                 for alias in ((item.get("name"), *item.get("aliases", [])) if isinstance(item, dict) else (item,))
             )),
            None,
        )
        return (
            {"country": country_name, "state": state_name, "district": district_name}
            if district_name else {}
        )
    matches = [
        (candidate_state, candidate_district.get("name") if isinstance(candidate_district, dict) else candidate_district)
        for candidate_state, state_data in states.items()
        for districts in [state_data.get("districts", []) if isinstance(state_data, dict) else state_data]
        for candidate_district in districts
        if any(
            " ".join(district.split()).casefold() == " ".join(alias.split()).casefold()
            for alias in (
                (candidate_district.get("name"), *candidate_district.get("aliases", []))
                if isinstance(candidate_district, dict) else (candidate_district,)
            )
        )
    ]
    return (
        {"country": country_name, "state": matches[0][0], "district": matches[0][1]}
        if len(matches) == 1 else {}
    )


def geography_options(country: str | None = None, state: str | None = None) -> dict[str, list[str]]:
    countries = sorted(GEOGRAPHY)
    country = canonical_name(GEOGRAPHY, country)
    state = canonical_name(GEOGRAPHY[country]["states"], state) if country and state else None
    if country:
        states = sorted(GEOGRAPHY[country]["states"])
    else:
        states = []
    state_data = GEOGRAPHY[country]["states"][state] if country and state else []
    district_values = state_data.get("districts", []) if isinstance(state_data, dict) else state_data
    districts = sorted(item.get("name") if isinstance(item, dict) else item for item in district_values)
    return {"countries": countries, "states": states, "districts": districts}
