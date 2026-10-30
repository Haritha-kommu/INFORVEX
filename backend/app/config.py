import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _csv_setting(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


def _bool_setting(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _int_setting(name: str, default: str) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return int(default)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'newsphere.db'}")
    feeds: tuple[str, ...] = _csv_setting("NEWSSPHERE_FEEDS")
    frontend_origins: tuple[str, ...] = _csv_setting("FRONTEND_ORIGINS", "http://localhost:5173,http://localhost:5174")
    scheduler_enabled: bool = _bool_setting("SCHEDULER_ENABLED")
    collection_interval_minutes: int = _int_setting("COLLECTION_INTERVAL_MINUTES", "120")
    admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "").strip()
    retention_days: int = _int_setting("RETENTION_DAYS", "7")
    raw_data_directory: Path = Path(os.getenv("RAW_DATA_DIRECTORY", str(BASE_DIR / "data" / "raw")))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    bigdata_enabled: bool = _bool_setting("BIGDATA_ENABLED")
    analytics_enabled: bool = _bool_setting("ANALYTICS_ENABLED")
    spacy_model: str = os.getenv("SPACY_MODEL", "en_core_web_sm").strip()


settings = Settings()
