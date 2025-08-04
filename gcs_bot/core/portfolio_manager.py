# src/core/portfolio_manager.py (NOVO ARQUIVO)

from gcs_bot.utils.logger import logger

class PortfolioManager:
    """Gestor de portfólio para simulação e tracking de capital."""
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.trading_capital_usdt = initial_capital
        self.trading_btc_balance = 0.0
        logger.info(f"Portfólio inicializado com ${initial_capital:,.2f} USDT.")

    def update_on_buy(self, cost_usdt: float, quantity_btc: float):
        """Atualiza o portfólio após uma compra."""
        self.trading_capital_usdt -= cost_usdt
        self.trading_btc_balance += quantity_btc
        logger.debug(f"Portfólio Atualizado (COMPRA): Saldo USDT: {self.trading_capital_usdt:.2f}, Saldo BTC: {self.trading_btc_balance:.8f}")

    def update_on_sell(self, revenue_usdt: float, quantity_btc: float):
        """Atualiza o portfólio após uma venda."""
        self.trading_capital_usdt += revenue_usdt
        self.trading_btc_balance -= quantity_btc
        logger.debug(f"Portfólio Atualizado (VENDA): Saldo USDT: {self.trading_capital_usdt:.2f}, Saldo BTC: {self.trading_btc_balance:.8f}")

    def get_total_portfolio_value_usdt(self, current_btc_price: float) -> float:
        """Calcula o valor total do portfólio em USDT."""
        if not current_btc_price or current_btc_price <= 0:
            return self.trading_capital_usdt
        return self.trading_capital_usdt + (self.trading_btc_balance * current_btc_price)