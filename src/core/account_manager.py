# src/core/account_manager.py (NOVO ARQUIVO)

from binance.client import Client
from binance.exceptions import BinanceAPIException
from src.logger import logger
from src.config_manager import settings

class AccountManager:
    def __init__(self, binance_client: Client):
        self.client = binance_client
        # Define o ativo de cotação (ex: USDT) a partir das configurações
        self.quote_asset = settings.SYMBOL.replace("BTC", "")

    def get_quote_asset_balance(self) -> float:
        """
        Busca o saldo livre do ativo de cotação (ex: USDT) na conta da Binance.
        Retorna 0.0 se o cliente não estiver disponível ou em caso de erro.
        """
        if not self.client:
            logger.warning("Cliente Binance não disponível. Retornando saldo 0.")
            # Em modo de simulação, poderíamos retornar um valor fixo se quiséssemos.
            return 0.0

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