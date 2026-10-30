import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.orchestration import claim_database_lock, release_database_lock
from app.database import Base
from app.models import CollectionLock


@pytest.fixture
def lock_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'scheduler-lock.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        engine.dispose()


def test_collection_and_cleanup_owners_are_mutually_exclusive(lock_database):
    first_session = lock_database()
    second_session = lock_database()
    try:
        claim_database_lock(first_session, 101)
        first_session.commit()

        with pytest.raises(RuntimeError, match="already in progress"):
            claim_database_lock(second_session, -202)
        second_session.rollback()

        assert second_session.get(CollectionLock, 1).run_id == 101
    finally:
        release_database_lock(first_session, 101)
        first_session.close()
        second_session.close()


def test_lock_is_released_after_failure(lock_database):
    session = lock_database()
    try:
        owner_id = -303
        claim_database_lock(session, owner_id)
        session.commit()

        try:
            raise RuntimeError("simulated cleanup failure")
        except RuntimeError:
            session.rollback()
        finally:
            release_database_lock(session, owner_id)

        assert session.get(CollectionLock, 1).run_id is None
    finally:
        session.close()
