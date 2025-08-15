import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.models import Base

# Use an in-memory SQLite database for testing
TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def postgres_manager():
    """Returns a PostgresManager instance for testing, using an in-memory SQLite DB."""
    # Dummy config, as we're overriding the engine
    config = {
        "user": "test", "password": "test", "host": "localhost", "port": "5432", "dbname": "test"
    }

    # Patch the __init__ method to prevent it from creating a real engine
    with patch.object(PostgresManager, '__init__', lambda s, c: None) as mock_init:
        manager = PostgresManager(config)

        # Now, set up the engine and session for the in-memory SQLite DB
        engine = create_engine(TEST_DB_URL)
        Base.metadata.create_all(engine)
        manager.engine = engine
        manager.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        yield manager

        Base.metadata.drop_all(engine)

def test_init(postgres_manager):
    """Tests the initialization of the PostgresManager."""
    assert postgres_manager.engine is not None
    assert postgres_manager.SessionLocal is not None

def test_create_tables(postgres_manager):
    """Tests the create_tables method."""
    # The tables should have been created by the fixture.
    # We can check if the tables exist in the database.
    with postgres_manager.get_db() as db:
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")).scalar() is not None
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio_snapshots'")).scalar() is not None
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='deposits'")).scalar() is not None
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='price_history'")).scalar() is not None
