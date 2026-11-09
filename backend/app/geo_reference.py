"""Load the maintained geography reference without inventing article metadata.

Country coverage follows ISO 3166-1. Administrative coverage is intentionally
partial and limited to the relationships present in the local reference.
"""

import json
from pathlib import Path

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "geography.json"
REFERENCE = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
GEOGRAPHY = REFERENCE["countries"]

# Load additional India district reference data separately.
ADDITIONAL_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "geography.india-geoboundaries.json"
)

if ADDITIONAL_REFERENCE_PATH.exists():
    additional_reference = json.loads(
        ADDITIONAL_REFERENCE_PATH.read_text(encoding="utf-8")
    )

    for country_name, country_data in additional_reference.get(
        "countries", {}
    ).items():
        if country_name not in GEOGRAPHY:
            continue

        for state_name, state_data in country_data.get(
            "states", {}
        ).items():
            existing_state = GEOGRAPHY[country_name]["states"].get(
                state_name
            )

            if existing_state is not None and not existing_state.get(
                "districts"
            ):
                existing_state["districts"] = state_data.get(
                    "districts", []
                )

BRAZIL_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "geography.brazil-candidate.json"
)

if BRAZIL_REFERENCE_PATH.exists():
    brazil_reference = json.loads(
        BRAZIL_REFERENCE_PATH.read_text(encoding="utf-8")
    )

    for country_name, country_data in brazil_reference.get(
        "countries", {}
    ).items():
        if country_name not in GEOGRAPHY:
            continue

        existing_states = GEOGRAPHY[country_name].setdefault(
            "states", {}
        )

        for state_name, state_data in country_data.get(
            "states", {}
        ).items():
            existing_state = existing_states.get(state_name)

            if existing_state is None:
                existing_states[state_name] = state_data
            elif not existing_state.get("districts"):
                existing_state["districts"] = state_data.get(
                    "districts", []
                )


FRANCE_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "geography.france-candidate.json"
)

if FRANCE_REFERENCE_PATH.exists():
    france_reference = json.loads(
        FRANCE_REFERENCE_PATH.read_text(encoding="utf-8")
    )

    for country_name, country_data in france_reference.get(
        "countries", {}
    ).items():
        if country_name not in GEOGRAPHY:
            continue

        existing_states = GEOGRAPHY[country_name].setdefault(
            "states", {}
        )

        for state_name, state_data in country_data.get(
            "states", {}
        ).items():
            existing_state = existing_states.get(state_name)

            if existing_state is None:
                existing_states[state_name] = state_data
            elif not existing_state.get("districts"):
                existing_state["districts"] = state_data.get(
                    "districts", []
                )



AUSTRALIA_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "geography.australia-candidate.json"
)

if AUSTRALIA_REFERENCE_PATH.exists():
    australia_reference = json.loads(
        AUSTRALIA_REFERENCE_PATH.read_text(encoding="utf-8")
    )

    for country_name, country_data in australia_reference.get(
        "countries", {}
    ).items():
        if country_name not in GEOGRAPHY:
            continue

        existing_states = GEOGRAPHY[country_name].setdefault(
            "states", {}
        )

        for state_name, state_data in country_data.get(
            "states", {}
        ).items():
            existing_state = existing_states.get(state_name)
            candidate_districts = state_data.get("districts", [])

            if existing_state is None:
                existing_states[state_name] = state_data
                continue

            # Preserve legacy city entries while converting lists
            # into the dictionary format used by the new reference.
            if isinstance(existing_state, list):
                existing_state = {"districts": existing_state}
                existing_states[state_name] = existing_state

            if isinstance(existing_state, dict):
                existing_districts = existing_state.setdefault(
                    "districts", []
                )

                existing_names = {
                    (
                        item.get("name")
                        if isinstance(item, dict)
                        else item
                    ).casefold()
                    for item in existing_districts
                }

                for item in candidate_districts:
                    item_name = (
                        item.get("name")
                        if isinstance(item, dict)
                        else item
                    )

                    if item_name.casefold() not in existing_names:
                        existing_districts.append(item)
                        existing_names.add(item_name.casefold())


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

def load_geography_from_database() -> bool:
    """Load the saved geography reference without replacing its shared dictionary."""
    from .database import SessionLocal
    from .models import GeographyReference

    with SessionLocal() as db:
        reference = db.get(GeographyReference, "global")

        if reference is None:
            return False

        data = reference.data

        if not isinstance(data, dict) or not isinstance(
            data.get("countries"), dict
        ):
            raise ValueError("Invalid geography reference stored in database")

        countries = data["countries"]

        if not countries:
            raise ValueError("Geography reference in database is empty")

        GEOGRAPHY.clear()
        GEOGRAPHY.update(countries)

    return True
