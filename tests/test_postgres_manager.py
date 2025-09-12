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
    with patch.object(PostgresManager, '__init__', lambda s: None) as mock_init:
        manager = PostgresManager()

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

from decimal import Decimal
from jules_bot.database.models import Trade

def test_create_tables(postgres_manager):
    """Tests the create_tables method."""
    # The tables should have been created by the fixture.
    # We can check if the tables exist in the database.
    with postgres_manager.get_db() as db:
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")).scalar() is not None
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_status'")).scalar() is not None
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='price_history'")).scalar() is not None

def test_update_trade_status_and_quantity(postgres_manager):
    """
    Tests that the update_trade_status_and_quantity method correctly updates a trade.
    """
    # Arrange
    trade_id = "test-update-123"
    with postgres_manager.get_db() as db:
        # Create a dummy trade to update
        dummy_trade = Trade(
            trade_id=trade_id,
            status="OPEN",
            quantity=Decimal("1.0"),
            # Add other required fields with dummy data
            run_id="test_run",
            environment="test",
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            order_type="buy",
            price=Decimal("50000.0"),
            usd_value=Decimal("50000.0"),
            exchange="binance"
        )
        db.add(dummy_trade)
        db.commit()

    # Act
    new_status = "CLOSED"
    new_quantity = Decimal("0.0")
    postgres_manager.update_trade_status_and_quantity(trade_id, new_status, new_quantity)

    # Assert
    with postgres_manager.get_db() as db:
        updated_trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
        assert updated_trade is not None
        assert updated_trade.status == new_status
        assert updated_trade.quantity == new_quantity
