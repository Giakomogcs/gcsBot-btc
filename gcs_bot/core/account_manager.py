# src/core/account_manager.py (VERSÃO CORRIGIDA)

from binance.client import Client
from binance.exceptions import BinanceAPIException
from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings

class AccountManager:
    def __init__(self, binance_client: Client):
        self.client = binance_client
        self.quote_asset = settings.app.symbol.replace("BTC", "")

    def get_quote_asset_balance(self) -> float:
        """
        Busca o saldo livre do ativo de cotação (ex: USDT) na conta da Binance.
        Esta versão foi corrigida para funcionar corretamente tanto em modo real quanto testnet.
        """
        # Se o cliente não foi inicializado (modo offline), não há o que fazer.
        if not self.client:
            logger.warning("Cliente Binance não disponível (modo offline). Retornando saldo 100")
            return 100

        try:
            # Esta chamada funciona tanto para a conta real quanto para a testnet,
            # dependendo de como o 'self.client' foi inicializado.
            account_info = self.client.get_account()
            
            # Procura o ativo de cotação (ex: USDT) nos saldos da conta.
            balance_info = next(
                (item for item in account_info['balances'] if item['asset'] == self.quote_asset),
                None
            )
            
            if balance_info:
                free_balance = float(balance_info['free'])
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