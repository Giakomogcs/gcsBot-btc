import logging
import pandas as pd
import uuid
from jules_bot.core_logic.trader import Trader

class MockTrader(Trader):
    """
    Simulates a cryptocurrency exchange for backtesting purposes.
    It is driven by the backtesting engine, which feeds it the current price
    and timestamp at each step of the simulation.
    """
    def __init__(self, initial_balance_usd: float, commission_fee_percent: float, symbol: str):
        self.symbol = symbol
        self.initial_balance = initial_balance_usd
        self.usd_balance = initial_balance_usd
        self.btc_balance = 0.0
        self.commission_rate = commission_fee_percent / 100.0

        self._current_price = 0.0
        self._current_timestamp = pd.Timestamp.now(tz='UTC')

        logging.info(f"MockTrader initialized. Initial balance: ${self.usd_balance:,.2f} USD.")

    def set_current_time_and_price(self, timestamp: pd.Timestamp, price: float):
        """Allows the backtesting engine to set the current time and price."""
        self._current_timestamp = timestamp
        self._current_price = price

    def get_current_price(self) -> float:
        """Returns the 'close' price for the current simulation step."""
        return self._current_price

    def get_current_timestamp(self) -> pd.Timestamp:
        """Returns the timestamp for the current simulation step."""
        return self._current_timestamp

    def execute_buy(self, amount_usdt: float) -> tuple[bool, dict]:
        """
        Simulates a market buy order.
        The `amount_usdt` is the gross value of the asset to be purchased.
        The commission is calculated on this amount and added to the total cost.
        """
        price = self.get_current_price()
        if price <= 0:
            return False, {"error": "Invalid price."}

        quantity_bought = amount_usdt / price
        commission = amount_usdt * self.commission_rate
        total_cost = amount_usdt + commission

        if self.usd_balance < total_cost:
            logging.warning(f"Insufficient funds. Required: ${total_cost:,.2f}, Available: ${self.usd_balance:,.2f}.")
            return False, {"error": "Insufficient USD balance."}

        self.usd_balance -= total_cost
        self.btc_balance += quantity_bought

        trade_data = {
            "trade_id": str(uuid.uuid4()),
            "symbol": self.symbol,
            "price": price,
            "quantity": quantity_bought,
            "usd_value": amount_usdt, # Gross value before commission
            "commission": commission,
            "timestamp": self.get_current_timestamp()
        }
        return True, trade_data

    def execute_sell(self, position_data: dict) -> tuple[bool, dict]:
        """Simulates a market sell order."""
        quantity_to_sell = position_data.get('quantity')
        if self.btc_balance < quantity_to_sell:
            logging.warning(f"Insufficient BTC to sell. Required: {quantity_to_sell}, Available: {self.btc_balance}")
            return False, {"error": "Insufficient BTC balance."}

        price = self.get_current_price()
        usd_value = quantity_to_sell * price
        commission = usd_value * self.commission_rate
        net_usd_value = usd_value - commission

        self.btc_balance -= quantity_to_sell
        self.usd_balance += net_usd_value

        exit_data = {
            "price": price,
            "quantity": quantity_to_sell,
            "usd_value": net_usd_value,
            "commission": commission,
            "timestamp": self.get_current_timestamp()
        }
        return True, exit_data

    def get_account_balance(self) -> float:
        """
        Returns the cash balance in USD.
        """
        return self.usd_balance

    def get_crypto_balance_in_usd(self) -> float:
        """
        Returns the value of the crypto balance in USD.
        """
        return self.btc_balance * self.get_current_price()

    def get_total_portfolio_value(self) -> float:
        """
        Returns the total portfolio value in USD (cash + value of BTC holdings).
        """
        current_price = self.get_current_price()
        btc_value_in_usd = self.btc_balance * current_price
        return self.usd_balance + btc_value_in_usd
