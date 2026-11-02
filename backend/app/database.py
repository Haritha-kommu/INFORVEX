
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def ensure_schema(database_engine=engine) -> None:
    """Apply additive compatibility changes without resetting existing data."""

    Base.metadata.create_all(bind=database_engine)

    inspector = inspect(database_engine)
    existing_tables = set(inspector.get_table_names())

    if "articles" not in existing_tables:
        return

    relevant_tables = (
        "articles",
        "feed_executions",
        "collection_runs",
        "agent_executions",
    )

    table_columns = {
        table: {
            column["name"]
            for column in inspector.get_columns(table)
        }
        for table in relevant_tables
        if table in existing_tables
    }

    statements = []

    if "location_provenance" not in table_columns.get("articles", set()):
        statements.append(
            "ALTER TABLE articles "
            "ADD COLUMN location_provenance "
            "VARCHAR(30) NOT NULL DEFAULT 'unknown'"
        )

    if "location_confidence" not in table_columns.get("articles", set()):
        statements.append(
            "ALTER TABLE articles "
            "ADD COLUMN location_confidence VARCHAR(20)"
        )

    if "inserted_count" not in table_columns.get("feed_executions", set()):
        statements.append(
            "ALTER TABLE feed_executions "
            "ADD COLUMN inserted_count INTEGER NOT NULL DEFAULT 0"
        )

    if "duplicate_count" not in table_columns.get("feed_executions", set()):
        statements.append(
            "ALTER TABLE feed_executions "
            "ADD COLUMN duplicate_count INTEGER NOT NULL DEFAULT 0"
        )

    if "last_heartbeat_at" not in table_columns.get("collection_runs", set()):
        statements.append(
            "ALTER TABLE collection_runs "
            "ADD COLUMN last_heartbeat_at TIMESTAMP"
        )

    if "run_id" not in table_columns.get("agent_executions", set()):
        statements.append(
            "ALTER TABLE agent_executions "
            "ADD COLUMN run_id INTEGER"
        )

    if "last_heartbeat_at" not in table_columns.get("agent_executions", set()):
        statements.append(
            "ALTER TABLE agent_executions "
            "ADD COLUMN last_heartbeat_at TIMESTAMP"
        )

    if statements:
        with database_engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
