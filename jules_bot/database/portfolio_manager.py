from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Iterator, Optional
from decimal import Decimal

from jules_bot.database.portfolio_models import Base, PortfolioSnapshot, FinancialMovement
from jules_bot.utils.logger import logger

class PortfolioManager:
    def __init__(self, session_local: sessionmaker):
        """
        Initializes the PortfolioManager with an existing sessionmaker
        to share the same database connection pool.
        """
        self.SessionLocal = session_local
        # Extract the engine from the sessionmaker's configuration
        self.engine = self.SessionLocal.kw['bind']
        self.create_tables()

    def create_tables(self):
        """Creates the portfolio-related tables in the database if they don't exist."""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Successfully created or verified portfolio tables (portfolio_snapshots, financial_movements).")
        except Exception as e:
            logger.error(f"Failed to create portfolio tables: {e}", exc_info=True)
            raise

    @contextmanager
    def get_db(self) -> Iterator[Session]:
        """Provides a transactional scope around a series of operations."""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def create_portfolio_snapshot(self, snapshot_data: dict) -> Optional[PortfolioSnapshot]:
        """
        Creates a new portfolio snapshot record in the database.
        """
        with self.get_db() as db:
            try:
                # Calculate evolution vs previous snapshot
                last_snapshot = self.get_latest_snapshot(db)
                evolution = None
                if last_snapshot:
                    current_value = Decimal(snapshot_data['total_portfolio_value_usd'])
                    previous_value = Decimal(last_snapshot.total_portfolio_value_usd)
                    if previous_value > Decimal('0'):
                        evolution = ((current_value / previous_value) - Decimal('1')) * Decimal('100')

                snapshot_data['evolution_percent_vs_previous'] = evolution

                new_snapshot = PortfolioSnapshot(**snapshot_data)
                db.add(new_snapshot)
                db.commit()
                db.refresh(new_snapshot)
                logger.info(f"Successfully created new portfolio snapshot with ID: {new_snapshot.id}")
                return new_snapshot
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to create portfolio snapshot: {e}", exc_info=True)
                return None

    def create_financial_movement(self, movement_type: str, amount_usd: Decimal, notes: str, transaction_id: Optional[str] = None) -> Optional[FinancialMovement]:
        """
        Records a financial movement (deposit or withdrawal) in the database.
        """
        with self.get_db() as db:
            try:
                new_movement = FinancialMovement(
                    transaction_id=transaction_id,
                    movement_type=movement_type,
                    amount_usd=amount_usd,
                    notes=notes
                )
                db.add(new_movement)
                db.commit()
                db.refresh(new_movement)
                logger.info(f"Successfully recorded financial movement: {new_movement.movement_type} of ${new_movement.amount_usd}")
                return new_movement
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to record financial movement: {e}", exc_info=True)
                return None

    def get_financial_movement_by_transaction_id(self, transaction_id: str) -> Optional[FinancialMovement]:
        """Retrieves a financial movement by its transaction ID."""
        with self.get_db() as db:
            return db.query(FinancialMovement).filter(FinancialMovement.transaction_id == transaction_id).first()

    def get_latest_snapshot(self, db: Optional[Session] = None) -> Optional[PortfolioSnapshot]:
        """
        Retrieves the most recent portfolio snapshot from the database.
        Can use an existing session or create a new one.
        """
        if db:
            return db.query(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.timestamp)).first()

        with self.get_db() as new_db:
            return new_db.query(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.timestamp)).first()

    def get_all_snapshots(self):
        """Retrieves all portfolio snapshots, ordered by timestamp."""
        with self.get_db() as db:
            return db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp).all()

    def get_portfolio_history(self, limit: int = 100) -> list[PortfolioSnapshot]:
        """
        Retrieves a recent history of portfolio snapshots, ordered from oldest to newest.
        """
        with self.get_db() as db:
            # Fetches the most recent `limit` snapshots
            snapshots = db.query(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.timestamp)).limit(limit).all()
            # Reverse the list to return them in chronological order (oldest to newest)
            return snapshots[::-1]
