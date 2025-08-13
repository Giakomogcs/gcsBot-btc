import asyncio
import json
import logging
import os
from aiohttp import web
from jules_bot.services.status_service import StatusService
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core.market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)

class WebSocketService:
    def __init__(self, app: web.Application):
        self._clients = set()
        self._app = app
        self._status_service = None
        self._config_manager = None
        self._market_data_provider = None
        self._db_manager = None
        self.background_task = None

    async def _initialize_services(self, environment: str):
        """Initializes all necessary services."""
        if self._status_service is None:
            self._config_manager = ConfigManager()
            db_config = self._config_manager.get_db_config('POSTGRES')
            self._db_manager = PostgresManager(config=db_config)
            self._market_data_provider = MarketDataProvider(self._db_manager)
            self._status_service = StatusService(self._db_manager, self._config_manager, self._market_data_provider)
            logger.info(f"WebSocketService services initialized for environment: {environment}")

    async def handle_connection(self, request):
        """Handles a new WebSocket connection."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info(f"New WebSocket client connected. Total clients: {len(self._clients)}")

        try:
            # The first message from the client should be the mode (e.g., 'test' or 'trade')
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    environment = msg.data.strip().lower()
                    logger.info(f"Client selected environment: {environment}")

                    # Initialize services with the correct mode
                    await self._initialize_services(environment)

                    # Start the background task if it's not already running
                    if self.background_task is None or self.background_task.done():
                        self.background_task = asyncio.create_task(self.start_background_task(environment))
                        logger.info("Started status update background task.")

                    # Keep the connection alive, listening for close signals
                    await self.keep_alive(ws)

                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket connection closed with exception {ws.exception()}")

        finally:
            self._clients.remove(ws)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self._clients)}")
            if not self._clients and self.background_task:
                self.background_task.cancel()
                self.background_task = None
                logger.info("No more clients, stopping status update background task.")
        return ws

    async def keep_alive(self, ws):
        """Listens for client messages, primarily to detect disconnection."""
        async for msg in ws:
            if msg.type == web.WSMsgType.CLOSE:
                break

    async def start_background_task(self, environment: str):
        """The main background loop for broadcasting status updates."""
        bot_id = f"jules_{environment}_bot"
        symbol = "BTC/USDT"

        while self._clients:
            try:
                exchange_manager = ExchangeManager(mode=environment)

                # 1. Fetch market data
                market_data = self._market_data_provider.get_latest_data(symbol)
                current_price = market_data.get('close', 0)

                # 2. Get reconciled open positions
                open_positions = self._status_service.get_reconciled_open_positions(
                    exchange_manager, environment, bot_id, current_price
                )

                # 3. Get buy signal status
                buy_signal_status = self._status_service.get_buy_signal_status(
                    market_data, len(open_positions)
                )

                # 4. Get trade history
                trade_history = self._status_service.get_trade_history(environment)

                # 5. Get wallet balances
                wallet_balances = self._status_service.get_wallet_balances(exchange_manager)

                # 6. Assemble and broadcast the payload
                status_payload = {
                    "mode": environment,
                    "symbol": symbol.replace('/', ''),
                    "current_btc_price": current_price,
                    "open_positions_status": open_positions,
                    "buy_signal_status": buy_signal_status,
                    "trade_history": trade_history,
                    "wallet_balances": wallet_balances,
                }

                await self.broadcast(json.dumps(status_payload, default=str))

            except Exception as e:
                logger.error(f"Error in status update loop: {e}", exc_info=True)
                # Broadcast an error message to clients
                await self.broadcast(json.dumps({"error": str(e)}))

            await asyncio.sleep(5) # Update interval
        logger.info("Background task finished.")

    async def broadcast(self, message: str):
        """Sends a message to all connected clients."""
        if not self._clients:
            return

        # Create a copy of the set to avoid issues with clients disconnecting during iteration
        for ws in list(self._clients):
            if not ws.closed:
                try:
                    await ws.send_str(message)
                except ConnectionResetError:
                    logger.warning("Failed to send to a client: connection reset.")
                except Exception as e:
                    logger.error(f"Error sending to client: {e}")
