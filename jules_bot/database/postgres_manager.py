import json
import logging
import os
import uuid
from decimal import Decimal
from typing import Optional, Iterator
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, desc, and_, not_, text, inspect, asc
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from jules_bot.core.schemas import TradePoint
from jules_bot.database.base import Base
from jules_bot.database.models import Trade, BotStatus, PriceHistory
from jules_bot.database.portfolio_models import PortfolioSnapshot, FinancialMovement
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager

class PostgresManager:
    def __init__(self, config_manager=None):
        if config_manager is None:
            # Import the global singleton if no specific instance is provided.
            from jules_bot.utils.config_manager import config_manager as global_config_manager
            config_manager = global_config_manager

        # The global config_manager is a singleton that initializes itself on import.
        # It reads the BOT_NAME environment variable at that time, so we can trust
        # that config_manager.bot_name is already correctly set.
        self.config_manager = config_manager
        db_config = self.config_manager.get_section("POSTGRES")

        db_user = db_config.get("user")
        db_password = db_config.get("password")
        db_host = db_config.get("host")
        db_port = db_config.get("port")
        db_name = db_config.get("dbname")

        if not all([db_user, db_password, db_host, db_port, db_name]):
            raise ValueError("One or more database configuration values are missing. Check your .env file.")

        # Sanitize bot name for schema (e.g., 'gcs-bot' -> 'gcs_bot')
        self.bot_name = config_manager.bot_name.replace("-", "_")

        self.db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        self.engine = create_engine(
            self.db_url,
            connect_args={
                'connect_timeout': 5,
                # Each bot operates in its own schema for data isolation.
                'options': f'-csearch_path={self.bot_name},public'
            },
            # Add pool_pre_ping to handle connections that may have been closed by the DB server.
            pool_pre_ping=True
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self._initialized = False
        self.initialize_db()

    def initialize_db(self):
        """
        Cria schema, tabelas e executa migrações.
        """
        if self._initialized:
            return
        self.create_schema()
        self.create_tables()
        self._run_migrations()
        self._initialized = True

    def create_schema(self):
        """
        Cria um novo schema para o bot se ele não existir.
        """
        with self.engine.connect() as connection:
            try:
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.bot_name}"))
                connection.commit()
                logger.info(f"Schema '{self.bot_name}' created or already exists.")
            except Exception as e:
                logger.error(f"Failed to create schema '{self.bot_name}': {e}")
                raise

    def _run_migrations(self):
        inspector = inspect(self.engine)
        with self.engine.connect() as connection:
            try:
                # Migration for 'trades' table
                if inspector.has_table("trades", schema=self.bot_name):
                    trade_columns = [c['name'] for c in inspector.get_columns('trades', schema=self.bot_name)]
                    if 'binance_trade_id' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'binance_trade_id' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f'ALTER TABLE {self.bot_name}.trades ADD COLUMN binance_trade_id INTEGER'))
                    if 'is_trailing' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'is_trailing' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f"ALTER TABLE {self.bot_name}.trades ADD COLUMN is_trailing BOOLEAN NOT NULL DEFAULT FALSE"))
                    if 'highest_price_since_breach' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'highest_price_since_breach' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f"ALTER TABLE {self.bot_name}.trades ADD COLUMN highest_price_since_breach NUMERIC(20, 8)"))
                    
                    # Migration for Intelligent Trailing Stop columns
                    if 'is_smart_trailing_active' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'is_smart_trailing_active' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f"ALTER TABLE {self.bot_name}.trades ADD COLUMN is_smart_trailing_active BOOLEAN NOT NULL DEFAULT FALSE"))
                    
                    if 'smart_trailing_activation_price' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'smart_trailing_activation_price' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f"ALTER TABLE {self.bot_name}.trades ADD COLUMN smart_trailing_activation_price NUMERIC(20, 8)"))

                    if 'smart_trailing_highest_profit' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'smart_trailing_highest_profit' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f"ALTER TABLE {self.bot_name}.trades ADD COLUMN smart_trailing_highest_profit NUMERIC(20, 8)"))
                    
                    if 'current_trail_percentage' not in trade_columns:
                        logger.info(f"Running migration: Adding missing column 'current_trail_percentage' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            connection.execute(text(f"ALTER TABLE {self.bot_name}.trades ADD COLUMN current_trail_percentage NUMERIC(10, 5)"))
                    
                    if 'remaining_quantity' not in trade_columns:
                        logger.info(f"Running migration: Adding and backfilling 'remaining_quantity' to table '{self.bot_name}.trades'")
                        with connection.begin():
                            # 1. Add the column, allowing nulls for back-filling
                            connection.execute(text(f'ALTER TABLE {self.bot_name}.trades ADD COLUMN remaining_quantity NUMERIC(20, 8)'))
                            
                            # 2. Set a baseline of 0 for all trades
                            logger.info("Back-filling 'remaining_quantity': setting to 0 for all trades initially.")
                            connection.execute(text(f'UPDATE {self.bot_name}.trades SET remaining_quantity = 0'))

                            # 3. For open buy trades, set remaining_quantity to the original quantity
                            logger.info("Back-filling 'remaining_quantity': setting to full quantity for open buys.")
                            connection.execute(text(f'''
                                UPDATE {self.bot_name}.trades
                                SET remaining_quantity = quantity
                                WHERE status = 'OPEN' AND order_type = 'buy'
                            '''))
                            
                            # 4. Now that all rows are populated, enforce the NOT NULL constraint
                            logger.info("Finalizing 'remaining_quantity' migration: setting column to NOT NULL.")
                            connection.execute(text(f'ALTER TABLE {self.bot_name}.trades ALTER COLUMN remaining_quantity SET NOT NULL'))

                # Migration for 'bot_status' table
                if inspector.has_table("bot_status", schema=self.bot_name):
                    status_columns = [c['name'] for c in inspector.get_columns('bot_status', schema=self.bot_name)]
                    if 'last_buy_condition' not in status_columns:
                        logger.info(f"Running migration: Adding missing column 'last_buy_condition' to table '{self.bot_name}.bot_status'")
                        with connection.begin():
                            connection.execute(text(f'ALTER TABLE {self.bot_name}.bot_status ADD COLUMN last_buy_condition VARCHAR'))

            except Exception as e:
                logger.error(f"Failed to run migration: {e}")

    def check_connection(self) -> tuple[bool, Optional[str]]:
        """
        Verifica se a conexão com o banco de dados pode ser estabelecida.
        Retorna uma tupla (bool, Optional[str]) indicando sucesso e uma mensagem de erro.
        """
        try:
            connection = self.engine.connect()
            connection.close()
            return True, None
        except Exception as e:
            # Retorna a mensagem de erro para ser exibida ao usuário
            return False, str(e)

    def create_tables(self):
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def get_db(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def write_bot_status(self, bot_id: str, mode: str, status_data: dict):
        logger.info(f"DB: Attempting to write status for bot_id='{bot_id}'")
        with self.get_db() as db:
            try:
                bot_status = db.query(BotStatus).filter(BotStatus.bot_id == bot_id).first()
                if bot_status:
                    logger.info(f"DB: Found existing status for '{bot_id}'. Updating.")
                    for key, value in status_data.items():
                        setattr(bot_status, key, value)
                else:
                    logger.info(f"DB: No existing status for '{bot_id}'. Creating new entry.")
                    bot_status = BotStatus(bot_id=bot_id, mode=mode, **status_data)
                    db.add(bot_status)
                db.commit()
                logger.info(f"DB: Successfully committed status for bot_id='{bot_id}'.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to write bot status to PostgreSQL for bot_id='{bot_id}': {e}")

    def get_bot_status(self, bot_id: str) -> Optional[BotStatus]:
        """Fetches the status of a bot from the database."""
        logger.info(f"DB: Attempting to read status for bot_id='{bot_id}'")
        with self.get_db() as db:
            try:
                status = db.query(BotStatus).filter(BotStatus.bot_id == bot_id).first()
                if status:
                    logger.info(f"DB: Found status for bot_id='{bot_id}'.")
                else:
                    logger.warning(f"DB: No status found for bot_id='{bot_id}'.")
                return status
            except Exception as e:
                logger.error(f"Failed to get bot status for {bot_id}: {e}", exc_info=True)
                return None

    def get_portfolio_history(self, bot_name: str, limit: int = 100) -> list[PortfolioSnapshot]:
        """
        Fetches the recent portfolio history for a given bot.
        Note: This queries within the schema of the currently configured bot.
        """
        with self.get_db() as db:
            try:
                # This query will implicitly use the bot's schema defined in the engine's search_path
                query = db.query(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.timestamp)).limit(limit)
                snapshots = query.all()
                return snapshots
            except Exception as e:
                logger.error(f"Failed to get portfolio history for bot '{bot_name}': {e}", exc_info=True)
                return []

    def log_trade(self, trade_point: TradePoint):
        """
        Logs a trade to the database. It can handle both creating a new trade
        and updating an existing one based on the 'trade_id'.
        It also robustly converts float values from TradePoint to Decimal for the DB model.
        """
        with self.get_db() as db:
            try:
                # Sanitize the input data to only include keys that correspond to Trade model columns
                valid_columns = {c.name for c in Trade.__table__.columns}
                trade_data_for_db = {k: v for k, v in trade_point.__dict__.items() if k in valid_columns}

                # Convert any float values to Decimal to ensure type safety with the database model.
                # This is the bridge between the float-based TradePoint and the Decimal-based Trade model.
                for key, value in trade_data_for_db.items():
                    if isinstance(value, float):
                        trade_data_for_db[key] = Decimal(str(value))

                # If timestamp is provided as a Unix timestamp (int), convert it to datetime
                if 'timestamp' in trade_data_for_db and isinstance(trade_data_for_db['timestamp'], int):
                    from datetime import datetime
                    # Timestamps can be in seconds or milliseconds. We'll check the magnitude to decide.
                    timestamp_val = trade_data_for_db['timestamp']
                    if timestamp_val > 10**12:  # Likely milliseconds
                        trade_data_for_db['timestamp'] = datetime.fromtimestamp(timestamp_val / 1000)
                    else:  # Likely seconds
                        trade_data_for_db['timestamp'] = datetime.fromtimestamp(timestamp_val)

                # Check if a trade with this trade_id already exists
                existing_trade = db.query(Trade).filter(Trade.trade_id == trade_point.trade_id).first()

                if existing_trade:
                    # This is an update call (e.g., a sell closing a buy).
                    # We must not overwrite the original 'order_type' of 'buy'.
                    trade_data_for_db.pop('order_type', None)
                    
                    logger.info(f"Updating existing trade record for trade_id: {trade_point.trade_id}")
                    for key, value in trade_data_for_db.items():
                        if value is not None:
                            setattr(existing_trade, key, value)
                else:
                    # Create new trade
                    logger.info(f"Creating new trade record for trade_id: {trade_point.trade_id}")
                    
                    # --- ADDED LOGIC for remaining_quantity ---
                    # For new trades, remaining_quantity is initialized.
                    if trade_data_for_db.get('order_type') == 'buy':
                        # For a new buy, the remaining quantity is the full quantity.
                        trade_data_for_db['remaining_quantity'] = trade_data_for_db.get('quantity')
                    else:
                        # For sells or other initial types, remaining quantity is 0.
                        trade_data_for_db['remaining_quantity'] = Decimal('0')
                    # --- END ADDED LOGIC ---

                    logger.debug(f"Data for new Trade model: {trade_data_for_db}")
                    
                    new_trade = Trade(**trade_data_for_db)
                    db.add(new_trade)

                db.commit()
                logger.info(f"Successfully logged '{trade_point.order_type}' for trade_id: {trade_point.trade_id}")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to log trade to PostgreSQL: {e}", exc_info=True)
                raise

    def get_price_data(self, measurement: str, start_date: str = "-30d", end_date: str = "now()") -> pd.DataFrame:
        """
        Fetches price data from the database for a specific measurement within a given date range.
        `start_date` and `end_date` should be in a format that PostgreSQL can understand,
        e.g., 'YYYY-MM-DD HH:MI:SS' or relative like '-30d'.
        """
        logger.info(f"DB: Fetching price data for {measurement} from {start_date} to {end_date}")
        with self.get_db() as db:
            try:
                # The query now correctly uses the date range to filter data at the database level.
                query = db.query(PriceHistory).filter(
                    PriceHistory.symbol == measurement,
                    PriceHistory.timestamp >= text(f"now() - interval '{start_date.replace('-', '')}'") if '-' in start_date else text(f"'{start_date}'"),
                    PriceHistory.timestamp <= text("now()") if end_date == "now()" else text(f"'{end_date}'")
                ).order_by(PriceHistory.timestamp)

                df = pd.read_sql(query.statement, self.engine, index_col='timestamp')

                if df.empty:
                    logger.warning(f"DB: No price data found for {measurement} in the specified range.")

                return df
            except Exception as e:
                logger.error(f"DB: Failed to get price data: {e}", exc_info=True)
                return pd.DataFrame()

    def get_oldest_open_buy_trade(self) -> Optional[Trade]:
        """
        Fetches the oldest open 'buy' trade from the database.
        This is used for FIFO sell logic.
        """
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(
                    and_(
                        Trade.status == "OPEN",
                        Trade.order_type == "buy"
                    )
                ).order_by(asc(Trade.timestamp)).first()
                return trade
            except Exception as e:
                logger.error(f"Failed to get oldest open buy trade: {e}", exc_info=True)
                return None

    def get_open_positions(self, environment: str, bot_id: Optional[str] = None, symbol: Optional[str] = None) -> list:
        """
        Fetches open positions for a given environment.
        Can optionally filter by bot_id (for backtesting) and symbol.
        Returns a list of Trade model instances, sorted by most recent.
        """
        with self.get_db() as db:
            try:
                filters = [
                    Trade.status == "OPEN",
                    Trade.environment == environment
                ]
                # O filtro por bot_id (que é na verdade run_id) foi removido daqui
                # porque estava causando um bug na TUI. A TUI passava o bot_name,
                # que nunca correspondia a um run_id. A conexão já está no escopo
                # do schema do bot, então a filtragem por run_id não é estritamente
                # necessária para a operação normal e deve ser usada apenas em
                # contextos específicos como backtesting, o que pode exigir uma função separada.
                if symbol:
                    filters.append(Trade.symbol == symbol)

                # MODIFIED: Added order_by clause to sort by timestamp descending
                query = db.query(Trade).filter(and_(*filters)).order_by(desc(Trade.timestamp))

                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get open positions from DB: {e}")
                raise

    def get_treasury_positions(self, environment: str, bot_id: Optional[str] = None) -> list:
        """
        Fetches all trades marked as 'TREASURY' for the current environment.
        """
        with self.get_db() as db:
            try:
                query = db.query(Trade).filter(
                    and_(
                        Trade.status == "TREASURY",
                        Trade.environment == environment
                    )
                )
                if bot_id:
                    query = query.filter(Trade.run_id == bot_id)

                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get treasury positions from DB: {e}", exc_info=True)
                return []

    def get_trade_by_trade_id(self, trade_id: str) -> Optional[Trade]:
        """Fetches a trade by its unique trade_id and returns the SQLAlchemy model instance."""
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
                return trade
            except Exception as e:
                logger.error(f"Failed to get trade by trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def update_trade_status(self, trade_id: str, new_status: str):
        """Updates the status of a specific trade in the database."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update status.")
                    return

                logger.info(f"Updating status for trade {trade_id} from '{trade_to_update.status}' to '{new_status}'.")
                trade_to_update.status = new_status
                db.commit()
                logger.info(f"Successfully updated status for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update trade status for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def atomically_set_trade_status(self, trade_id: str, current_status: str, new_status: str) -> bool:
        """
        Atomically updates the status of a trade from current_status to new_status.
        This is a race-condition-safe operation.
        Returns True if the update was successful (1 row affected), False otherwise.
        """
        with self.get_db() as db:
            try:
                # The update is performed directly on the query object
                # The WHERE clause ensures we only update if the status is the one we expect
                result = db.query(Trade).filter(
                    Trade.trade_id == trade_id,
                    Trade.status == current_status
                ).update({Trade.status: new_status}, synchronize_session=False)

                db.commit()

                # The 'result' is the number of rows affected.
                # If it's 1, the update was successful.
                # If it's 0, it means the trade wasn't in the 'current_status' (it was likely already changed by another process).
                if result == 1:
                    logger.info(f"Atomically updated status for trade {trade_id} from '{current_status}' to '{new_status}'.")
                    return True
                else:
                    logger.warning(f"Atomic update failed for trade {trade_id}. Expected status '{current_status}', but it was not found or already changed.")
                    db.rollback() # Rollback to be safe, though no change was committed
                    return False

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to atomically update trade status for trade_id '{trade_id}': {e}", exc_info=True)
                # We re-raise the exception because this is an unexpected error (e.g., DB connection lost)
                raise

    def update_trade_status_and_quantity(self, trade_id: str, new_status: str, new_quantity: Decimal):
        """Updates the status and quantity of a specific trade in a single transaction."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update status and quantity.")
                    return

                logger.info(f"Updating trade {trade_id}: Status -> {new_status}, Quantity -> {new_quantity:.8f}")
                trade_to_update.status = new_status
                trade_to_update.quantity = new_quantity
                db.commit()
                logger.info(f"Successfully updated status and quantity for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update status and quantity for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def update_trade_status_and_context(self, trade_id: str, new_status: str, context_update: dict):
        """Updates the status and merges new data into the decision_context of a specific trade."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update status and context.")
                    return

                logger.info(f"Updating status for trade {trade_id} to '{new_status}' and updating context.")
                trade_to_update.status = new_status

                # Merge the new context with the existing one
                existing_context = trade_to_update.decision_context or {}
                existing_context.update(context_update)
                trade_to_update.decision_context = existing_context

                db.commit()
                logger.info(f"Successfully updated status and context for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update status and context for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def update_trade_sell_target(self, trade_id: str, new_target: Decimal):
        """Updates the sell_target_price of a specific trade in the database."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update sell target.")
                    return

                trade_to_update.sell_target_price = new_target
                db.commit()

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update sell target for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def get_trade_by_binance_trade_id(self, binance_trade_id: int) -> Optional[Trade]:
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.binance_trade_id == binance_trade_id).first()
                return trade
            except Exception as e:
                logger.error(f"Failed to get trade by binance_trade_id '{binance_trade_id}': {e}")
                return None

    def get_trade_by_exchange_order_id(self, exchange_order_id: str) -> Optional[Trade]:
        """Fetches a trade by its exchange_order_id."""
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.exchange_order_id == exchange_order_id).first()
                return trade
            except Exception as e:
                logger.error(f"Failed to get trade by exchange_order_id '{exchange_order_id}': {e}", exc_info=True)
                return None

    def update_trade_binance_id(self, trade_id: str, binance_trade_id: int):
        """Updates the binance_trade_id of a specific trade."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update binance_trade_id.")
                    return

                logger.info(f"Updating binance_trade_id for trade {trade_id} to {binance_trade_id}.")
                trade_to_update.binance_trade_id = binance_trade_id
                db.commit()
                logger.info(f"Successfully updated binance_trade_id for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update binance_trade_id for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def has_open_positions(self) -> bool:
        with self.get_db() as db:
            try:
                return db.query(Trade).filter(Trade.status == "OPEN").first() is not None
            except Exception as e:
                logger.error(f"Failed to check for open positions: {e}", exc_info=True)
                raise

    def get_all_trades_in_range(self, mode: Optional[str] = None, symbol: Optional[str] = None, bot_id: Optional[str] = None, start_date: any = None, end_date: any = "now()", order_type: Optional[str] = None, status: Optional[str] = None):
        with self.get_db() as db:
            try:
                query = db.query(Trade).order_by(desc(Trade.timestamp))

                filters = []
                if mode:
                    filters.append(Trade.environment == mode)
                if symbol:
                    filters.append(Trade.symbol == symbol)
                if order_type:
                    filters.append(Trade.order_type == order_type)
                if status:
                    filters.append(Trade.status == status)
                # The bot_id (run_id) filter is intentionally omitted here for the difficulty
                # calculation. We want the difficulty to be based on the bot's overall
                # recent activity, even across restarts, to prevent the reset issue.
                # The query is already scoped to the bot's schema and environment (mode).
                pass

                # Handle start_date
                if start_date:
                    if isinstance(start_date, datetime):
                        filters.append(Trade.timestamp >= start_date)
                    elif isinstance(start_date, str) and '-' in start_date:
                        filters.append(Trade.timestamp >= text(f"now() - interval '{start_date.replace('-', '')}'"))
                    else:
                        filters.append(Trade.timestamp >= text(f"'{start_date}'"))

                # Handle end_date
                if end_date:
                    if isinstance(end_date, datetime):
                        filters.append(Trade.timestamp <= end_date)
                    else:
                        filters.append(Trade.timestamp <= text("now()") if end_date == "now()" else text(f"'{end_date}'"))

                if filters:
                    query = query.filter(and_(*filters))

                trades = query.all()
                return trades

            except Exception as e:
                logger.error(f"Failed to get all trades from DB: {e}", exc_info=True)
                raise

    def get_trades_by_run_id(self, run_id: str) -> list:
        """Fetches all trades associated with a specific run_id."""
        with self.get_db() as db:
            try:
                query = db.query(Trade).filter(Trade.run_id == run_id).order_by(Trade.timestamp)
                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get trades by run_id '{run_id}': {e}", exc_info=True)
                raise

    def get_closed_sell_trades_for_run(self, run_id: str) -> list[Trade]:
        """
        Fetches all successfully closed 'sell' trades for a specific run_id.
        This is the definitive source for calculating realized PnL for a run.
        """
        with self.get_db() as db:
            try:
                query = db.query(Trade).filter(
                    and_(
                        Trade.run_id == run_id,
                        Trade.order_type == 'sell',
                        Trade.status == 'CLOSED'
                    )
                ).order_by(Trade.timestamp)
                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get closed sell trades by run_id '{run_id}': {e}", exc_info=True)
                raise

    def get_all_trades_for_sync(self, environment: str, symbol: str) -> list[Trade]:
        """
        Fetches all trades for a given environment and symbol, without any status filters.
        This is crucial for the SynchronizationManager to get a complete history for its simulation.
        """
        with self.get_db() as db:
            try:
                filters = [
                    Trade.environment == environment,
                    Trade.symbol == symbol
                ]
                query = db.query(Trade).filter(and_(*filters)).order_by(Trade.timestamp)
                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get all trades for sync from DB: {e}")
                raise

    def get_last_binance_trade_id(self) -> int:
        """
        Fetches the ID of the most recent trade in the database based on binance_trade_id.
        This is used to know where to start the next sync from.
        """
        with self.get_db() as db:
            try:
                # No environment filter, we want the absolute last trade ID recorded for this bot
                last_trade = db.query(Trade).order_by(desc(Trade.binance_trade_id)).first()
                if last_trade and last_trade.binance_trade_id is not None:
                    logger.info(f"Last known Binance trade ID is {last_trade.binance_trade_id}")
                    return last_trade.binance_trade_id
                logger.info("No existing Binance trade ID found in the database, will sync from the beginning.")
                return 0
            except Exception as e:
                logger.error(f"Failed to get last binance trade ID from DB: {e}", exc_info=True)
                return 0

    def update_trade_quantity(self, trade_id: str, new_quantity: Decimal):
        """
        Updates the quantity of a specific trade in the database.
        This is used for partial sell logic, where the original buy position's
        quantity is reduced.
        """
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update quantity.")
                    return

                logger.info(f"Updating quantity for trade {trade_id} from {trade_to_update.quantity} to {new_quantity}.")
                trade_to_update.quantity = new_quantity
                db.commit()
                logger.info(f"Successfully updated quantity for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update trade quantity for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def update_trade_quantity_and_context(self, trade_id: str, new_quantity: Decimal, context_update: dict):
        """Updates the quantity and merges new data into the decision_context of a specific trade."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update quantity and context.")
                    return

                logger.info(f"Updating quantity for trade {trade_id} to {new_quantity} and updating context.")
                trade_to_update.quantity = new_quantity

                existing_context = trade_to_update.decision_context or {}
                existing_context.update(context_update)
                trade_to_update.decision_context = existing_context

                db.commit()
                logger.info(f"Successfully updated quantity and context for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update quantity and context for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def update_trade(self, trade_id: str, update_data: dict):
        """
        Dynamically updates a trade record in the database using a dictionary of fields.
        """
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update.")
                    return

                logger.info(f"Updating trade {trade_id} with data: {list(update_data.keys())}")

                # Critical fix: Prevent overwriting the original 'buy' order type when a sell occurs.
                # A 'sell' action should update a trade, not change its fundamental type from buy to sell.
                update_data.pop('order_type', None)

                # If timestamp is provided as a Unix timestamp (int), convert it to datetime
                if 'timestamp' in update_data and isinstance(update_data['timestamp'], int):
                    from datetime import datetime
                    # Timestamps can be in seconds or milliseconds. We'll check the magnitude to decide.
                    timestamp_val = update_data['timestamp']
                    if timestamp_val > 10**12:  # Likely milliseconds
                        update_data['timestamp'] = datetime.fromtimestamp(timestamp_val / 1000)
                    else:  # Likely seconds
                        update_data['timestamp'] = datetime.fromtimestamp(timestamp_val)
                
                valid_columns = {c.name for c in Trade.__table__.columns}
                
                for key, value in update_data.items():
                    if key in valid_columns:
                        setattr(trade_to_update, key, value)
                    else:
                        logger.warning(f"'{key}' is not a valid column in the 'trades' table. Skipping.")

                db.commit()
                logger.info(f"Successfully updated trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to perform dynamic update for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def find_linked_sell_trade(self, buy_trade_id: str) -> Optional[Trade]:
        """
        Finds the sell trade that is linked to a specific buy trade.
        """
        with self.get_db() as db:
            try:
                sell_trade = db.query(Trade).filter(
                    Trade.linked_trade_id == buy_trade_id,
                    Trade.order_type == 'sell'
                ).first()
                return sell_trade
            except Exception as e:
                logger.error(f"Failed to find linked sell trade for buy_trade_id '{buy_trade_id}': {e}", exc_info=True)
                return None

    def clear_all_tables(self):
        with self.get_db() as db:
            try:
                db.execute(text(f"TRUNCATE TABLE {self.bot_name}.trades, {self.bot_name}.bot_status, {self.bot_name}.price_history RESTART IDENTITY;"))
                db.commit()
                logger.info("All tables cleared successfully.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear tables: {e}")

    def query_first_timestamp(self, measurement: str) -> Optional[pd.Timestamp]:
        """
        Queries the very first timestamp for a specific measurement in the table.
        """
        logger.info(f"Querying first timestamp for measurement '{measurement}'...")
        with self.get_db() as db:
            try:
                from jules_bot.database.models import PriceHistory
                from sqlalchemy import asc
                first_record = db.query(PriceHistory).filter(PriceHistory.symbol == measurement).order_by(asc(PriceHistory.timestamp)).first()
                if not first_record:
                    logger.info(f"No data found in measurement '{measurement}'.")
                    return None
                first_timestamp = pd.to_datetime(first_record.timestamp).tz_localize('UTC')
                logger.info(f"First timestamp found in DB: {first_timestamp}")
                return first_timestamp
            except Exception as e:
                logger.error(f"Error querying first timestamp from PostgreSQL for measurement '{measurement}': {e}", exc_info=True)
                return None

    def clear_backtest_trades(self):
        """Deletes all trades from the 'trades' table where the environment is 'backtest'."""
        with self.get_db() as db:
            try:
                # Using text for a simple delete statement for clarity
                statement = text(f"DELETE FROM {self.bot_name}.trades WHERE environment = :env")
                result = db.execute(statement, {"env": "backtest"})
                db.commit()
                logger.info(f"Successfully cleared {result.rowcount} backtest trades from the database.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear backtest trades: {e}", exc_info=True)
                raise

    def clear_testnet_trades(self):
        """Deletes all trades from the 'trades' table where the environment is 'test'."""
        with self.get_db() as db:
            try:
                statement = text(f"DELETE FROM {self.bot_name}.trades WHERE environment = :env")
                result = db.execute(statement, {"env": "test"})
                db.commit()
                logger.info(f"Successfully cleared {result.rowcount} testnet trades from the database.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear testnet trades: {e}", exc_info=True)
                raise