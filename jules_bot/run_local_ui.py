import asyncio
import os
import sys
import logging
from decimal import Decimal

# Ensure the project root is in the Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.services.status_service import StatusService
from jules_bot.bot.command_manager import CommandManager
from jules_bot.ui.display_manager import DisplayManager
from jules_bot.utils.logger import logger

# --- Main Application Runner ---

class LocalUIApp:
    """
    Manages the lifecycle of services and the Textual UI, running them in a single process.
    """
    def __init__(self, mode: str):
        if mode not in ["trade", "test"]:
            raise ValueError("Mode must be either 'trade' or 'test'")
        self.mode = mode
        self.symbol = "BTC/USDT"
        self.bot_id = f"jules_{self.mode}_bot"
        self.update_interval_sec = 5  # 5 seconds, same as the old websocket

        # Initialize core services
        logger.info("Initializing services...")
        self.config_manager = ConfigManager()
        db_config = self.config_manager.get_db_config('POSTGRES')
        self.db_manager = PostgresManager(config=db_config)
        self.market_data_provider = MarketDataProvider(self.db_manager)
        self.exchange_manager = ExchangeManager(mode=self.mode)
        self.status_service = StatusService(self.db_manager, self.config_manager, self.market_data_provider)
        self.command_manager = CommandManager(self.db_manager, self.exchange_manager, self.bot_id, self.symbol)
        logger.info("Services initialized successfully.")

        # Initialize the Textual App
        self.app = DisplayManager(mode=self.mode, command_manager=self.command_manager)

    def get_status_payload(self) -> dict:
        """
        Fetches all status information from the StatusService, mirroring the old
        WebSocket payload.
        """
        try:
            # 1. Fetch market data
            market_data = self.market_data_provider.get_latest_data(self.symbol)
            current_price = market_data.get('close', '0')

            # 2. Get reconciled open positions
            open_positions = self.status_service.get_reconciled_open_positions(
                self.exchange_manager, self.mode, self.bot_id, Decimal(current_price)
            )

            # 3. Get buy signal status
            buy_signal_status = self.status_service.get_buy_signal_status(
                market_data, len(open_positions)
            )

            # 4. Get trade history
            trade_history = self.status_service.get_trade_history(self.mode)

            # 5. Get wallet balances
            wallet_balances = self.status_service.get_wallet_balances(self.exchange_manager)

            # 6. Assemble the payload
            return {
                "mode": self.mode,
                "symbol": self.symbol.replace('/', ''),
                "current_btc_price": current_price,
                "open_positions_status": open_positions,
                "buy_signal_status": buy_signal_status,
                "trade_history": trade_history,
                "wallet_balances": wallet_balances,
            }
        except Exception as e:
            logger.error(f"Error generating status payload: {e}", exc_info=True)
            return {"error": str(e)}

    async def _update_ui_data(self) -> None:
        """
        Coroutine that fetches data and schedules a UI update on the main thread.
        """
        logger.debug("Fetching status payload...")
        payload = self.get_status_payload()
        # call_soon is used to pass data from this background task to the UI thread safely
        self.app.call_soon(self.app.update_data, payload)

    async def _periodic_update_task(self) -> None:
        """The main background loop for periodically updating the UI."""
        logger.info(f"Starting periodic UI update task every {self.update_interval_sec} seconds.")
        while True:
            try:
                await self._update_ui_data()
            except Exception as e:
                logger.error(f"Error in periodic update task: {e}", exc_info=True)
            await asyncio.sleep(self.update_interval_sec)

    def run(self):
        """
        Starts the Textual application and the background update task.
        """
        async def run_app_with_background_task():
            # Run the first update immediately
            await self._update_ui_data()

            # Start the periodic background task
            asyncio.create_task(self._periodic_update_task())

            # Run the Textual app (this is a blocking call)
            await self.app.run_async()

        try:
            logger.info(f"Starting Local UI in '{self.mode.upper()}' mode...")
            asyncio.run(run_app_with_background_task())
            logger.info("Local UI has been shut down.")
        except KeyboardInterrupt:
            logger.info("Local UI stopped manually.")
        except Exception as e:
            logger.critical(f"A critical error occurred: {e}", exc_info=True)

def main():
    """
    Entry point for the local UI runner.
    Parses command-line arguments to determine the bot's mode.
    """
    # Default to 'test' mode if no arguments are provided
    mode = "test"
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["live", "trade"]:
        mode = "trade"

    local_ui = LocalUIApp(mode=mode)
    local_ui.run()

if __name__ == '__main__':
    main()
