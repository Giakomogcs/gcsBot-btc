# src/core/account_manager.py (VERSÃO CORRIGIDA)

from binance.client import Client
from binance.exceptions import BinanceAPIException
from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings

class AccountManager:
    def __init__(self, binance_client: Client):
        self.client = binance_client
        self.base_asset = "BTC"
        self.quote_asset = settings.app.symbol.replace("BTC", "")

    def get_base_asset_balance(self) -> float:
        """Busca o saldo livre do ativo base (ex: BTC) na conta da Binance."""
        if not self.client:
            logger.warning("Cliente Binance não disponível (modo offline). Retornando saldo 0.")
            return 0.0
        try:
            account_info = self.client.get_account()
            balance_info = next(
                (item for item in account_info['balances'] if item['asset'] == self.base_asset),
                None
            )
            if balance_info:
                return float(balance_info['free'])
            else:
                logger.warning(f"Ativo {self.base_asset} não encontrado na conta.")
                return 0.0
        except BinanceAPIException as e:
            logger.error(f"Erro na API da Binance ao buscar saldo de BTC: {e}", exc_info=True)
            return 0.0
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar saldo de BTC: {e}", exc_info=True)
            return 0.0

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

    def update_on_sell(self, quantity_btc: float):
        """
        Places a market sell order on Binance.
        """
        if not self.client or settings.app.force_offline_mode:
            logger.warning(f"OFFLINE MODE: Simulating sell of {quantity_btc:.8f} BTC.")
            return True # Simulate success

        try:
            logger.info(f"Attempting to place market SELL order for {quantity_btc:.8f} BTC...")
            order = self.client.order_market_sell(symbol=settings.app.symbol, quantity=quantity_btc)
            logger.info(f"SUCCESS: Market SELL order placed: {order}")
            return True
        except BinanceAPIException as e:
            logger.error(f"Binance API Error on SELL: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error on SELL: {e}", exc_info=True)
            return False

    def update_on_buy(self, quote_order_qty: float):
        """
        Places a market buy order on Binance.
        """
        if not self.client or settings.app.force_offline_mode:
            logger.warning(f"OFFLINE MODE: Simulating buy with {quote_order_qty:.2f} USDT.")
            return True # Simulate success

        try:
            logger.info(f"Attempting to place market BUY order for {quote_order_qty:.2f} USDT...")
            order = self.client.order_market_buy(symbol=settings.app.symbol, quoteOrderQty=quote_order_qty)
            logger.info(f"SUCCESS: Market BUY order placed: {order}")
            return True
        except BinanceAPIException as e:
            logger.error(f"Binance API Error on BUY: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error on BUY: {e}", exc_info=True)
            return False

    def get_open_orders(self) -> list:
        """
        Fetches open orders from Binance for the current symbol.
        """
        if not self.client or settings.app.force_offline_mode:
            logger.warning("OFFLINE MODE: Cannot fetch open orders.")
            return []

        try:
            open_orders = self.client.get_open_orders(symbol=settings.app.symbol)
            return open_orders
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching open orders: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching open orders: {e}", exc_info=True)
            return []

    def get_trade_history(self, limit: int = 10) -> list:
        """
        Fetches trade history from Binance for the current symbol.
        """
        if not self.client or settings.app.force_offline_mode:
            logger.warning("OFFLINE MODE: Cannot fetch trade history.")
            return []

        try:
            trades = self.client.get_my_trades(symbol=settings.app.symbol, limit=limit)
            return trades
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching trade history: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching trade history: {e}", exc_info=True)
            return []