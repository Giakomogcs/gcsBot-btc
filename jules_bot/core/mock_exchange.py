import logging
import pandas as pd
import uuid
from decimal import Decimal, getcontext
from jules_bot.core_logic.trader import Trader

getcontext().prec = 28

class MockTrader(Trader):
    def __init__(self, initial_balance_usd: Decimal, commission_fee_rate: Decimal, symbol: str):
        self.symbol = symbol
        self.initial_balance = Decimal(initial_balance_usd)
        self.usd_balance = Decimal(initial_balance_usd)
        self.btc_balance = Decimal('0.0')
        self.commission_rate = Decimal(commission_fee_rate)

        from jules_bot.utils.config_manager import config_manager as global_config_manager
        self.slippage_rate = Decimal(global_config_manager.get('BACKTEST', 'slippage_rate', fallback='0.0'))

        self._current_price = Decimal('0.0')
        self._current_timestamp = pd.Timestamp.now(tz='UTC')

        logging.info(f"MockTrader initialized. Initial balance: ${self.usd_balance:,.2f} USD. Slippage: {self.slippage_rate:.4%}")

    def set_current_time_and_price(self, timestamp: pd.Timestamp, price: Decimal):
        self._current_timestamp = timestamp
        self._current_price = Decimal(price)

    def get_current_price(self) -> Decimal:
        return self._current_price

    def get_current_timestamp(self) -> pd.Timestamp:
        return self._current_timestamp

    def get_commission(self) -> Decimal:
        return self.commission_rate

    def execute_buy(self, amount_usdt: Decimal, run_id: str, decision_context: dict) -> tuple[bool, dict]:
        price = self.get_current_price()
        if price <= 0:
            return False, {"error": "Invalid price."}

        # Apply slippage for buys (price is higher)
        execution_price = price * (Decimal('1') + self.slippage_rate)

        amount_usdt = Decimal(amount_usdt)
        # The quantity of crypto received is based on the amount spent on the asset itself.
        quantity_bought = amount_usdt / execution_price

        # Commission is calculated on the value of the asset at the execution price
        commission_usd = (quantity_bought * execution_price) * self.commission_rate
        total_cost = amount_usdt + commission_usd

        if self.usd_balance < total_cost:
            logging.warning(f"Insufficient funds. Required: ${total_cost:,.2f}, Available: ${self.usd_balance:,.2f}.")
            return False, {"error": "Insufficient USD balance."}

        self.usd_balance -= total_cost
        self.btc_balance += quantity_bought

        trade_data = {
            "trade_id": str(uuid.uuid4()), "symbol": self.symbol, "price": execution_price,
            "quantity": quantity_bought, "usd_value": amount_usdt,
            "commission_usd": commission_usd, "timestamp": self.get_current_timestamp()
        }
        return True, trade_data

    def execute_sell(self, position_data: dict, run_id: str, decision_context: dict) -> tuple[bool, dict]:
        quantity_to_sell = Decimal(position_data.get('quantity'))
        if self.btc_balance < quantity_to_sell:
            logging.warning(f"Insufficient BTC to sell. Required: {quantity_to_sell}, Available: {self.btc_balance}")
            return False, {"error": "Insufficient BTC balance."}

        price = self.get_current_price()

        # Apply slippage for sells (price is lower)
        execution_price = price * (Decimal('1') - self.slippage_rate)

        usd_value = quantity_to_sell * execution_price
        commission_usd = usd_value * self.commission_rate
        net_usd_value = usd_value - commission_usd

        self.btc_balance -= quantity_to_sell
        self.usd_balance += net_usd_value

        exit_data = {
            "price": execution_price, "quantity": quantity_to_sell,
            "usd_value": usd_value, # Return gross USD value before commission
            "commission_usd": commission_usd,
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
