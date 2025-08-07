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
    def __init__(self, db_manager, account_manager, exchange_manager):
        self.db_manager = db_manager
        self.account_manager = account_manager
        self.exchange_manager = exchange_manager
        self.config = settings
        self.strategy_config = self.config.trading_strategy
        self.recent_high_price = 0.0
        self.positions_pending_sale = set()
        os.makedirs(COMMANDS_DIR, exist_ok=True)
        self.initialize_price_tracker()

    def process_manual_commands(self):
        """Checks for and processes command files from the UI."""
        for command_file in os.listdir(COMMANDS_DIR):
            if command_file.endswith(".json"):
                filepath = os.path.join(COMMANDS_DIR, command_file)
                try:
                    with open(filepath, 'r') as f:
                        command_data = json.load(f)

                    logger.info(f"[COMMAND] Processing command: {command_data}")
                    self._execute_command(command_data)

                except Exception as e:
                    logger.error(f"[ERROR] Failed to process command file {command_file}: {e}")
                finally:
                    # Delete the file after processing, regardless of success
                    os.remove(filepath)

    def _execute_command(self, command: dict):
        """Routes the command to the appropriate handler function."""
        command_type = command.get("type")
        if command_type == "force_buy":
            self.force_manual_buy(command.get("amount_usd"))
        elif command_type == "force_sell":
            self.force_manual_sell(command.get("trade_id"))
        elif command_type == "to_treasury":
            self.force_convert_to_treasury(command.get("trade_id"))
        else:
            logger.warning(f"[WARNING] Unknown command type: {command_type}")

    def force_manual_sell(self, trade_id: str):
        """Forces the immediate market sale of an entire open position."""
        if not trade_id: return
        logger.info(f"--> [MANUAL CMD] Forcing sell for trade ID: {trade_id}")

        position = self.db_manager.get_trade_by_id(trade_id)
        if position is None or position.get('status') != 'OPEN':
            logger.error(f"Cannot force sell: Trade {trade_id} not found or not open.")
            return

        current_price = self.exchange_manager.get_current_price(self.config.app.symbol)
        if not current_price:
            logger.error(f"Cannot force sell: Could not get current price for {self.config.app.symbol}.")
            return

        self._sell_position(position, current_price)

    def force_convert_to_treasury(self, trade_id: str):
        """Manually closes a position without selling, flagging it as treasured."""
        if not trade_id: return
        logger.info(f"--> [MANUAL CMD] Converting trade ID: {trade_id} to treasury.")

        extra_fields = {"decision_data": json.dumps({"reason": "MANUAL_TREASURY"})}
        self.db_manager.update_trade_status(trade_id, 'CLOSED', extra_fields)

    def force_manual_buy(self, amount_usd: float):
        """Executes an immediate market buy for a specified USD amount."""
        if amount_usd is None or amount_usd <= 0:
            logger.error("[ERROR] Invalid amount for force_manual_buy.")
            return

        logger.info(f"--> [MANUAL CMD] Attempting to buy ${amount_usd} of BTC.")

        # We can reuse the _execute_buy_order logic, but we need the current price first.
        current_price = self.exchange_manager.get_current_price(self.config.app.symbol)
        if not current_price:
            logger.error("Could not get current price to execute manual buy.")
            return

        buy_successful = self.account_manager.update_on_buy(quote_order_qty=amount_usd)

        if buy_successful:
            quantity_btc = amount_usd / current_price
            trade_data = {
                "trade_id": str(uuid.uuid4()),
                "status": "OPEN",
                "entry_price": current_price,
                "quantity_btc": quantity_btc,
                "timestamp": datetime.now(timezone.utc),
                "decision_data": {"reason": "FORCE_MANUAL_BUY"},
            }
            self.db_manager.write_trade(trade_data)
            logger.info(f"Manual buy successful. New position opened at ${current_price:,.2f}")
        else:
            logger.error("Failed to execute manual buy order on the exchange.")

    def initialize_price_tracker(self):
        """Call this once on startup to set the initial price."""
        symbol = self.config.app.symbol
        self.recent_high_price = self.exchange_manager.get_current_price(symbol)
        if self.recent_high_price:
            logger.info(f"Price tracker initialized at: {self.recent_high_price}")
        else:
            logger.warning("[WARNING] Could not initialize price tracker. Will try again on next cycle.")

    def _check_and_execute_sells(self, current_price: float):
        """Evaluates each open position independently for a potential sale."""
        open_positions = self.db_manager.get_open_positions()

        if open_positions.empty:
            return

        for trade_id, position in open_positions.iterrows():
            if trade_id in self.positions_pending_sale:
                continue # Skip if already being processed

            if not current_price:
                logger.warning(f"[WARNING] Could not get current price for {self.config.app.symbol}. Skipping sell check.")
                continue

            entry_price = position['entry_price']
            pnl_percent = ((current_price - entry_price) / entry_price) * 100

            take_profit_target = self.strategy_config.take_profit_percentage
            if pnl_percent >= take_profit_target:
                logger.info(f"[SELL ACTION] Take-profit hit for position {trade_id} at {pnl_percent:.2f}%. Executing sale.")
                self.positions_pending_sale.add(trade_id)
                self._sell_position(position, current_price)

    def _sell_position(self, position, current_price):
        """Sells 100% of the position and updates the database."""
        quantity_to_sell = position['quantity_btc']

        # In a real scenario, you'd get the executed price from the exchange
        # For simplicity, we use the current price.
        sell_successful = self.account_manager.update_on_sell(quantity_btc=quantity_to_sell, current_price=current_price)

        if sell_successful:
            entry_cost = position['entry_price'] * quantity_to_sell
            exit_value = current_price * quantity_to_sell
            commission = (entry_cost + exit_value) * self.config.backtest.commission_rate
            net_pnl = exit_value - entry_cost - commission

            update_trade_data = {
                "trade_id": position.name,
                "status": "CLOSED",
                "entry_price": position['entry_price'],
                "quantity_btc": 0,
                "realized_pnl_usdt": position.get('realized_pnl_usdt', 0.0) + net_pnl,
                "timestamp": datetime.now(timezone.utc),
                "decision_data": {"exit_reason": "TAKE_PROFIT"}
            }
            self.db_manager.write_trade(update_trade_data)
            logger.info(f"Position {position.name} closed successfully. Realized PnL: ${net_pnl:.2f}")
        else:
            logger.error(f"Failed to execute sell order for position {position.name} on the exchange.")
            self.positions_pending_sale.remove(position.name) # Remove lock on failure


    def _check_and_execute_buys(self, current_price: float):
        """Observes the market for a dip to open a NEW position."""
        if self.db_manager.has_open_positions():
            return

        if not current_price:
            return

        if self.recent_high_price == 0.0:
            self.recent_high_price = current_price
            logger.info(f"Buy watcher initialized. Current peak price: {self.recent_high_price}")
            return

        if current_price > self.recent_high_price:
            self.recent_high_price = current_price
            return

        dip_percentage = ((current_price - self.recent_high_price) / self.recent_high_price) * 100
        buy_trigger = self.strategy_config.buy_on_dip_percentage

        if dip_percentage <= buy_trigger:
            logger.info(f"[BUY ACTION] Dip of {dip_percentage:.2f}% detected from peak of {self.recent_high_price} (Trigger: {buy_trigger}%). Executing new buy.")

            self._execute_buy_order(current_price)

            logger.info(f"Buy attempted. Resetting price peak tracker.")
            self.recent_high_price = 0.0

    def _execute_buy_order(self, current_price):
        """Opens a new position."""
        trade_size_usdt = 100.0 # Fixed trade size for simplicity

        buy_successful = self.account_manager.update_on_buy(quote_order_qty=trade_size_usdt)

        if buy_successful:
            quantity_btc = trade_size_usdt / current_price

            # CORREÇÃO: Informa o simulador sobre o BTC comprado para atualizar o saldo.
            # O `hasattr` garante que isso só aconteça no modo backtest sem quebrar o modo real.
            if hasattr(self.account_manager, 'credit_btc'):
                self.account_manager.credit_btc(quantity_btc)

            trade_data = {
                "trade_id": str(uuid.uuid4()),
                "status": "OPEN",
                "entry_price": current_price,
                "quantity_btc": quantity_btc,
                "timestamp": datetime.now(timezone.utc),
                "decision_data": {"reason": "BUY_THE_DIP"},
            }
            self.db_manager.write_trade(trade_data)
            logger.info(f"New position opened at ${current_price:,.2f}")
        else:
            logger.error("Failed to execute buy order on the exchange.")


    def manage_positions(self, current_price: float):
        """The main orchestrator, updated to separate buy and sell checks."""
        if not current_price:
            logger.warning("[WARNING] Invalid price received. Skipping position management cycle.")
            return
            
        self._check_and_execute_sells(current_price)
        self._check_and_execute_buys(current_price)

    def reconcile_states(self):
        """Compares the bot's internal state with the exchange's state."""
        logger.info("--- Starting State Reconciliation ---")
        try:
            local_positions = self.db_manager.get_open_positions()
            exchange_positions = self.exchange_manager.get_all_open_positions_from_exchange()

            local_quantity = local_positions['quantity_btc'].sum() if not local_positions.empty else 0
            exchange_quantity = sum(p['quantity'] for p in exchange_positions)

            logger.info(f"Local state: {len(local_positions)} positions, total quantity {local_quantity:.8f}")
            logger.info(f"Exchange state: {len(exchange_positions)} positions, total quantity {exchange_quantity:.8f}")

            if not abs(local_quantity - exchange_quantity) < 1e-8: # Compare with a small tolerance
                logger.warning("!!! STATE DISCREPANCY DETECTED !!!")
                logger.warning(f"Local DB quantity ({local_quantity}) does not match exchange quantity ({exchange_quantity}).")
                # In a more advanced implementation, you would trigger a process to resolve this.
                # For now, we just log the warning.
            else:
                logger.info("✅ State reconciliation successful. Local and exchange states are consistent.")

        except Exception as e:
            logger.error(f"An error occurred during state reconciliation: {e}", exc_info=True)