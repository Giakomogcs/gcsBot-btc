from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from typing import Optional
import time

class Trader:
    """
    Classe responsável por toda a comunicação com a API da corretora (Binance).
    """
    def __init__(self, mode: str = 'trade'):
        self.mode = mode
        self._client = self._init_binance_client()
        self.symbol = config_manager.get('APP', 'symbol')

    def _init_binance_client(self) -> Optional[Client]:
        """Inicializa e autentica o cliente da API da Binance com base no modo."""
        if self.mode == 'offline' or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning("Modo OFFLINE. Trader não se conectará.")
            return None

        use_testnet = self.mode == 'test'

        try:
            if use_testnet:
                binance_config = config_manager.get_section('BINANCE_TESTNET')
            else:
                binance_config = config_manager.get_section('BINANCE_LIVE')

            api_key = binance_config.get('api_key')
            api_secret = binance_config.get('api_secret')

            if not api_key or not api_secret:
                logger.error(f"API Key/Secret da Binance para o modo '{self.mode}' não encontradas.")
                return None

            client = Client(api_key, api_secret, tld='com', testnet=use_testnet)

            try:
                server_time = client.get_server_time()
                local_time = int(time.time() * 1000)
                time_diff = server_time['serverTime'] - local_time
                client.timestamp_offset = time_diff
                logger.info(f"Offset de tempo com o servidor da Binance ajustado em {time_diff} ms.")
            except Exception as e:
                logger.error(f"Não foi possível sincronizar o tempo com a Binance. Erro: {e}", exc_info=True)

            client.ping()
            logger.info(f"✅ Conexão com a Binance estabelecida com sucesso (Modo: {'TESTNET' if use_testnet else 'REAL'}).")
            return client
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"❌ Falha na conexão com a Binance: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ Ocorreu um erro inesperado ao inicializar o cliente Binance: {e}", exc_info=True)
            return None

    def execute_buy(self, amount_usdt: float) -> Optional[dict]:
        """Envia uma ordem de compra a mercado para a corretora."""
        if not self._client:
            logger.error("Cliente Binance não inicializado. Ordem de compra não pode ser enviada.")
            return None
        try:
            logger.info(f"TENTANDO EXECUTAR ORDEM DE COMPRA A MERCADO: {amount_usdt} USDT de {self.symbol}")
            order = self._client.order_market_buy(symbol=self.symbol, quoteOrderQty=amount_usdt)
            logger.info(f"✅ ORDEM DE COMPRA EXECUTADA COM SUCESSO: {order}")
            return order
        except Exception as e:
            logger.error(f"ERRO INESPERADO AO COLOCAR ORDEM DE COMPRA: {e}", exc_info=True)
            return None

    def execute_sell(self, position_data: dict) -> Optional[dict]:
        """Envia uma ordem de venda a mercado para a corretora."""
        if not self._client:
            logger.error("Cliente Binance não inicializado. Ordem de venda não pode ser enviada.")
            return None
        try:
            quantity = position_data.get('quantity')
            logger.info(f"TENTANDO EXECUTAR ORDEM DE VENDA A MERCADO: {quantity} de {self.symbol}")
            order = self._client.order_market_sell(symbol=self.symbol, quantity=quantity)
            logger.info(f"✅ ORDEM DE VENDA EXECUTADA COM SUCESSO: {order}")
            return order
        except Exception as e:
            logger.error(f"ERRO INESPERADO AO COLOCAR ORDEM DE VENDA: {e}", exc_info=True)
            return None

    def close_connection(self):
        """Closes the connection to the exchange."""
        if self._client:
            self._client.close_connection()
            logger.info("Conexão com a Binance fechada.")
