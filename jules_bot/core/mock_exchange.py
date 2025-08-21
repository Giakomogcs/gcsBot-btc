import logging
import pandas as pd
import uuid
from decimal import Decimal, getcontext
from jules_bot.core_logic.trader import Trader

getcontext().prec = 28

class MockTrader(Trader):
    def __init__(self, initial_balance_usd: Decimal, commission_fee_percent: Decimal, symbol: str):
        self.symbol = symbol
        self.initial_balance = Decimal(initial_balance_usd)
        self.usd_balance = Decimal(initial_balance_usd)
        self.btc_balance = Decimal('0.0')
        self.commission_rate = Decimal(commission_fee_percent) / Decimal('100.0')

        self._current_price = Decimal('0.0')
        self._current_timestamp = pd.Timestamp.now(tz='UTC')

        logging.info(f"MockTrader initialized. Initial balance: ${self.usd_balance:,.2f} USD.")

    def set_current_time_and_price(self, timestamp: pd.Timestamp, price: Decimal):
        self._current_timestamp = timestamp
        self._current_price = Decimal(price)

    def get_current_price(self) -> Decimal:
        return self._current_price

    def get_current_timestamp(self) -> pd.Timestamp:
        return self._current_timestamp

    def execute_buy(self, amount_usdt: Decimal, decision_context: dict = None) -> tuple[bool, dict]:
        price = self.get_current_price()
        if price <= 0:
            return False, {"error": "Invalid price."}

        amount_usdt = Decimal(amount_usdt)
        # In a real scenario, commission is often part of the quote quantity.
        # Here we simulate it being an additional cost for simplicity.
        commission = amount_usdt * self.commission_rate
        net_amount_usdt = amount_usdt - commission
        quantity_bought = net_amount_usdt / price

        if self.usd_balance < amount_usdt:
            logging.warning(f"Insufficient funds. Required: ${amount_usdt:,.2f}, Available: ${self.usd_balance:,.2f}.")
            return False, {"error": "Insufficient USD balance."}

        self.usd_balance -= amount_usdt
        self.btc_balance += quantity_bought

        trade_data = {
            "trade_id": str(uuid.uuid4()),
            "symbol": self.symbol,
            "price": price,
            "quantity": quantity_bought,
            "usd_value": amount_usdt, # Gross value including commission
            "commission": commission,
            "commission_asset": "USDT",
            "timestamp": self.get_current_timestamp(),
            "decision_context": decision_context or {}
        }
        return True, trade_data

    def execute_sell(self, position_data: dict) -> tuple[bool, dict]:
        quantity_to_sell = Decimal(position_data.get('quantity'))
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
            "symbol": self.symbol,
            "price": price, "quantity": quantity_to_sell,
            "usd_value": net_usd_value, "commission": commission,
            "timestamp": self.get_current_timestamp()
        }
        return True, exit_data

    def get_account_balance(self) -> Decimal:
        return self.usd_balance

    def get_crypto_balance_in_usd(self) -> Decimal:
        return self.btc_balance * self.get_current_price()

    def get_total_portfolio_value(self) -> Decimal:
        current_price = self.get_current_price()
        btc_value_in_usd = self.btc_balance * current_price
        return self.usd_balance + btc_value_in_usd
