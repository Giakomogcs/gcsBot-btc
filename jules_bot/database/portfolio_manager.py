from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Iterator, Optional

from jules_bot.database.portfolio_models import Base, PortfolioSnapshot, FinancialMovement
from jules_bot.utils.logger import logger

class PortfolioManager:
    def __init__(self, config: dict):
        self.db_url = f"postgresql+psycopg2://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['dbname']}"
        self.engine = create_engine(self.db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
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
                    current_value = snapshot_data['total_portfolio_value_usd']
                    previous_value = last_snapshot.total_portfolio_value_usd
                    if previous_value > 0:
                        evolution = ((current_value / previous_value) - 1) * 100

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

    def record_financial_movement(self, movement_data: dict) -> Optional[FinancialMovement]:
        """
        Records a financial movement (deposit or withdrawal) in the database.
        """
        with self.get_db() as db:
            try:
                new_movement = FinancialMovement(**movement_data)
                db.add(new_movement)
                db.commit()
                db.refresh(new_movement)
                logger.info(f"Successfully recorded financial movement: {new_movement.movement_type} of ${new_movement.amount_usd}")
                return new_movement
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to record financial movement: {e}", exc_info=True)
                return None

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
