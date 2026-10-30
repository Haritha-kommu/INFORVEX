
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

# Load the existing NewsSphere models and database tables.
from app.models import (
    Article,
    CollectionRun,
    FeedExecution,
    AgentExecution,
    CollectionLock,
)
from app.database import Base

BACKEND_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BACKEND_DIR / "newsphere.db"

TABLE_NAMES = [
    "articles",
    "collection_runs",
    "feed_executions",
    "agent_executions",
    "collection_lock",
]


def main():
    load_dotenv(BACKEND_DIR / ".env.cloud", override=True)
    cloud_url = os.getenv("CLOUD_DATABASE_URL", "").strip()

    if not cloud_url or "PASTE_YOUR_" in cloud_url:
        raise SystemExit(
            "CLOUD_DATABASE_URL is missing in backend/.env.cloud"
        )

    if not SQLITE_PATH.exists():
        raise SystemExit(f"SQLite database not found: {SQLITE_PATH}")

    # Use psycopg 3 for PostgreSQL connections.
    url = make_url(cloud_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername != "postgresql+psycopg":
        raise SystemExit(
            "Please use the Supabase PostgreSQL Session Pooler URI."
        )

    source_engine = create_engine(
        f"sqlite:///{SQLITE_PATH.as_posix()}"
    )
    target_engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"sslmode": "require"},
    )

    try:
        source_inspector = inspect(source_engine)
        source_table_names = set(source_inspector.get_table_names())

        missing = [
            name for name in TABLE_NAMES
            if name not in source_table_names
        ]
        if missing:
            raise SystemExit(f"Missing local tables: {missing}")

        # Confirm the cloud database connection before changing anything.
        with target_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Supabase connection successful.")

        # Create tables using the actual application models.
        Base.metadata.create_all(target_engine)

        # Reflect the source and destination table definitions.
        source_metadata = MetaData()
        source_metadata.reflect(
            bind=source_engine, only=TABLE_NAMES
        )
        target_metadata = MetaData()
        target_metadata.reflect(
            bind=target_engine, only=TABLE_NAMES
        )

        source_tables = {
            name: source_metadata.tables[name]
            for name in TABLE_NAMES
        }
        target_tables = {
            name: target_metadata.tables[name]
            for name in TABLE_NAMES
        }

        # Stop if destination tables contain any records.
        with target_engine.connect() as connection:
            cloud_counts = {
                name: connection.execute(
                    select(text("count(*)")).select_from(
                        target_tables[name]
                    )
                ).scalar_one()
                for name in TABLE_NAMES
            }

        if any(cloud_counts.values()):
            raise SystemExit(
                "Migration stopped because cloud tables are not empty. "
                f"Cloud row counts: {cloud_counts}"
            )

        with source_engine.connect() as connection:
            local_counts = {
                name: connection.execute(
                    select(text("count(*)")).select_from(
                        source_tables[name]
                    )
                ).scalar_one()
                for name in TABLE_NAMES
            }

        print("Local row counts:", local_counts)
        print("Cloud tables are empty. Copying data...")

        # All five tables are copied in one transaction.
        with target_engine.begin() as target_connection:
            with source_engine.connect() as source_connection:
                for name in TABLE_NAMES:
                    source_table = source_tables[name]
                    target_table = target_tables[name]
                    result = source_connection.execute(
                        select(source_table)
                    ).mappings()

                    batch = []
                    copied = 0

                    for row in result:
                        batch.append(dict(row))

                        if len(batch) >= 200:
                            target_connection.execute(
                                target_table.insert(), batch
                            )
                            copied += len(batch)
                            batch.clear()

                    if batch:
                        target_connection.execute(
                            target_table.insert(), batch
                        )
                        copied += len(batch)

                    print(f"Copied {name}: {copied} rows")

            # Reset PostgreSQL ID sequences to avoid future ID conflicts.
            for name in TABLE_NAMES:
                table = target_tables[name]
                if "id" not in table.c:
                    continue

                max_id = target_connection.execute(
                    select(text("max(id)")).select_from(table)
                ).scalar_one()

                if max_id is not None:
                    target_connection.execute(
                        text(
                            "SELECT setval("
                            "pg_get_serial_sequence(:table_name, 'id'), "
                            ":max_id, true)"
                        ),
                        {"table_name": name, "max_id": max_id},
                    )

        # Verify all table counts after migration.
        with target_engine.connect() as connection:
            final_counts = {
                name: connection.execute(
                    select(text("count(*)")).select_from(
                        target_tables[name]
                    )
                ).scalar_one()
                for name in TABLE_NAMES
            }

        print("\nLocal counts:", local_counts)
        print("Cloud counts:", final_counts)

        if local_counts != final_counts:
            raise SystemExit(
                "Count mismatch. Do not switch the application yet."
            )

        print("\nSUCCESS: All five table counts match.")

    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
