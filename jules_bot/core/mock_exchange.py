# File: gcs_bot/core/mock_exchange.py
import logging
import pandas as pd
import uuid

class MockExchangeManager:
    """
    Simulates a cryptocurrency exchange for backtesting purposes.
    It uses a historical data feed and manages a simulated account balance.
    """
    def __init__(self, historical_data: pd.DataFrame, initial_balance_usd: float, commission_fee_percent: float):
        self.historical_data = historical_data
        self.current_step = 0
        self.initial_balance = initial_balance_usd
        self.usd_balance = initial_balance_usd
        self.btc_balance = 0.0
        self.commission_rate = commission_fee_percent / 100.0
        logging.info(f"MockExchange initialized. Initial balance: ${self.usd_balance:,.2f} USD.")

    def get_current_price(self, symbol: str) -> float:
        """Returns the 'close' price for the current simulation step."""
        # NOTE: 'symbol' is ignored for now, assuming single-asset backtesting.
        return self.historical_data['close'].iloc[self.current_step]

    def get_current_timestamp(self) -> pd.Timestamp:
        """Returns the timestamp for the current simulation step."""
        return self.historical_data.index[self.current_step]

    def place_buy_order(self, symbol: str, usd_amount: float) -> tuple[bool, dict]:
        """Simulates a market buy order."""
        if self.usd_balance < usd_amount:
            logging.warning(f"Insufficient funds to place buy order of ${usd_amount:,.2f}.")
            return False, {"error": "Insufficient USD balance."}

        price = self.get_current_price(symbol)
        commission = usd_amount * self.commission_rate
        net_usd_amount = usd_amount - commission
        quantity_bought = net_usd_amount / price

        self.usd_balance -= usd_amount
        self.btc_balance += quantity_bought

        trade_data = {
            "trade_id": str(uuid.uuid4()),
            "symbol": symbol,
            "entry_price": price,
            "quantity": quantity_bought,
            "usd_value": usd_amount,
            "commission": commission,
            "timestamp": self.get_current_timestamp()
        }
        return True, trade_data

    def place_sell_order(self, symbol: str, quantity_to_sell: float) -> tuple[bool, dict]:
        """Simulates a market sell order."""
        if self.btc_balance < quantity_to_sell:
            logging.warning(f"Insufficient BTC to sell. Required: {quantity_to_sell}, Available: {self.btc_balance}")
            return False, {"error": "Insufficient BTC balance."}

        price = self.get_current_price(symbol)
        usd_value = quantity_to_sell * price
        commission = usd_value * self.commission_rate
        net_usd_value = usd_value - commission

        self.btc_balance -= quantity_to_sell
        self.usd_balance += net_usd_value

        exit_data = {
            "exit_price": price,
            "quantity": quantity_to_sell,
            "usd_value": net_usd_value,
            "commission": commission,
            "timestamp": self.get_current_timestamp()
        }
        return True, exit_data

    def advance_time(self) -> bool:
        """Moves the simulation to the next historical data point."""
        if self.current_step < len(self.historical_data) - 1:
            self.current_step += 1
            return True
        return False # End of data
