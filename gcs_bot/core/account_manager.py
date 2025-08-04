# src/core/account_manager.py (Final Version)

from binance.client import Client
from binance.exceptions import BinanceAPIException
from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings

class AccountManager:
    def __init__(self, binance_client: Client):
        self.client = binance_client
        # Define o ativo de cotação (ex: USDT) a partir das configurações
        self.quote_asset = settings.app.symbol.replace("BTC", "")

    def get_quote_asset_balance(self) -> float:
        """
        Busca o saldo livre do ativo de cotação (ex: USDT) na conta da Binance.
        """
        if not self.client or settings.app.use_testnet:
            logger.debug("Cliente Binance não disponível ou em modo testnet. Usando capital do portfólio de simulação.")
            # This is a placeholder for backtesting; the actual capital is managed by PortfolioManager
            return settings.backtest.initial_capital

        try:
            account_info = self.client.get_account()
            usdt_balance = next(
                (item for item in account_info['balances'] if item['asset'] == self.quote_asset),
                None
            )
            
            if usdt_balance:
                free_balance = float(usdt_balance['free'])
                logger.debug(f"Saldo de {self.quote_asset} consultado: {free_balance}")
                return free_balance
            else:
                logger.warning(f"Ativo {self.quote_asset} não encontrado na conta.")
                return 0.0
        except BinanceAPIException as e:
            logger.error(f"Erro na API da Binance ao buscar saldo: {e}", exc_info=True)
            return 0.0
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar saldo: {e}", exc_info=True)
            return 0.0