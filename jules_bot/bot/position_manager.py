import pandas as pd
import uuid
from datetime import datetime, timezone
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import settings
import os
import json
import time

COMMANDS_DIR = "commands"

class PositionManager:
    def __init__(self, db_manager, exchange_manager, market_data_provider):
        self.db_manager = db_manager
        self.exchange_manager = exchange_manager
        self.market_data_provider = market_data_provider
        self.strategy_config = settings.trading_strategy

        # CRITICAL: Load open positions from the database on startup
        self.open_positions = self._load_open_positions()
        logging.info(f"PositionManager initialized. Loaded {len(self.open_positions)} open position(s) from the database.")

    def _load_open_positions(self) -> list[dict]:
        """Fetches all trades marked as 'OPEN' from the database."""
        return self.db_manager.get_open_positions(bot_id="jules_bot_main") # Or a relevant bot_id

    def execute_buy(self, signal_data):
        """Executes a buy order and records the new open position in the database."""
        usd_amount = self.strategy_config.usd_per_trade
        success, exchange_data = self.exchange_manager.place_buy_order(
            symbol=signal_data['symbol'],
            usd_amount=usd_amount
        )

        if success:
            # Combine all data and persist the new open trade
            trade_data = {
                "bot_id": "jules_bot_main",
                "mode": "backtest", # This should be dynamic based on bot's mode
                "symbol": signal_data['symbol'],
                "strategy": self.strategy_config.name,
                **exchange_data
            }
            self.db_manager.open_trade(trade_data)
            self.open_positions.append(trade_data) # Update in-memory state as well
            logging.info(f"Successfully opened new position: {trade_data['trade_id']}")

    def check_for_exit(self, position):
        """Checks if an open position should be closed based on strategy rules."""
        # This is where your exit logic goes (e.g., check for take profit / stop loss)
        # For now, let's assume a simple rule.
        current_price = self.exchange_manager.get_current_price(position['symbol'])
        if current_price >= position['entry_price'] * 1.02: # Simple 2% take profit
            self.execute_sell(position)

    def execute_sell(self, position_to_close):
        """Executes a sell order and updates the position to 'CLOSED' in the database."""
        success, exchange_data = self.exchange_manager.place_sell_order(
            symbol=position_to_close['symbol'],
            quantity_to_sell=position_to_close['quantity']
        )

        if success:
            # Calculate P&L and create the update payload for the database
            pnl_usd = exchange_data['usd_value'] - position_to_close['usd_value']
            pnl_percent = (pnl_usd / position_to_close['usd_value']) * 100

            exit_payload = {
                "exit_price": exchange_data['exit_price'],
                "pnl_usd": pnl_usd,
                "pnl_percent": pnl_percent,
                "timestamp": exchange_data['timestamp']
            }
            
            self.db_manager.close_trade(trade_id=position_to_close['trade_id'], exit_data=exit_payload)
            # Remove from in-memory list of open positions
            self.open_positions = [p for p in self.open_positions if p['trade_id'] != position_to_close['trade_id']]
            logging.info(f"Successfully closed position: {position_to_close['trade_id']}. P&L: ${pnl_usd:,.2f}")

    def manage_positions(self):
        """The main loop for the manager, called on every bot cycle."""
        for position in list(self.open_positions): # Iterate over a copy
            self.check_for_exit(position)