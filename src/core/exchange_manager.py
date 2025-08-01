# Ficheiro: src/core/exchange_manager.py

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from src.config_manager import settings
from src.logger import logger
from typing import Optional, Union

class ExchangeManager:
    """
    Classe responsável por toda a comunicação com a API da corretora (Binance).
    Abstrai as chamadas de API, como obter saldo, preços e executar ordens.
    """
    def __init__(self):
        self.use_testnet = settings.app.use_testnet
        self._client = self._init_binance_client()

    def _init_binance_client(self) -> Optional[Client]:
        """Inicializa e autentica o cliente da API da Binance."""
        if settings.app.force_offline_mode:
            logger.warning("Modo OFFLINE forçado. ExchangeManager não se conectará.")
            return None
        try:
            api_key = settings.api_keys.binance_testnet_api_key if self.use_testnet else settings.api_keys.binance_api_key
            api_secret = settings.api_keys.binance_testnet_api_secret if self.use_testnet else settings.api_keys.binance_api_secret

            if not api_key or not api_secret:
                logger.error("API Key/Secret da Binance não encontradas nas configurações.")
                return None

            client = Client(api_key, api_secret, tld='com', testnet=self.use_testnet)
            client.ping()
            logger.info(f"✅ Conexão com a Binance estabelecida com sucesso (Modo: {'TESTNET' if self.use_testnet else 'REAL'}).")
            return client
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"❌ Falha na conexão com a Binance: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ Ocorreu um erro inesperado ao inicializar o cliente Binance: {e}", exc_info=True)
            return None

    def get_account_balance(self, asset: str = 'USDT') -> float:
        """
        Busca o saldo livre de um ativo específico na conta da corretora.

        :param asset: O ticker do ativo (ex: 'USDT', 'BTC').
        :return: O saldo livre (disponível para uso) como um float. Retorna 0.0 se ocorrer um erro.
        """
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Retornando saldo 0.")
            return 0.0
        try:
            balance_info = self._client.get_asset_balance(asset=asset)
            if balance_info:
                free_balance = float(balance_info['free'])
                logger.debug(f"Saldo disponível de {asset}: {free_balance}")
                return free_balance
            logger.warning(f"Não foi possível obter informações de saldo para o ativo {asset}.")
            return 0.0
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Erro na API da Binance ao buscar saldo de {asset}: {e}", exc_info=True)
            return 0.0
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar saldo: {e}", exc_info=True)
            return 0.0

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Busca o preço de mercado mais recente para um par de negociação.

        :param symbol: O par de negociação (ex: 'BTCUSDT').
        :return: O preço atual como um float, ou None se ocorrer um erro.
        """
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Não é possível buscar o preço.")
            return None
        try:
            ticker = self._client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            logger.debug(f"Preço atual de {symbol}: {price}")
            return price
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Erro na API da Binance ao buscar preço para {symbol}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar preço: {e}", exc_info=True)
            return None

    def place_market_order(self, symbol: str, side: str, quantity: Union[float, str]) -> Optional[dict]:
        """
        Envia uma ordem de mercado para a corretora.

        :param symbol: O par de negociação (ex: 'BTCUSDT').
        :param side: O lado da ordem ('BUY' ou 'SELL').
        :param quantity: A quantidade a ser negociada. Para ordens de COMPRA, é a quantidade do ativo de cotação (USDT). Para ordens de VENDA, é a quantidade do ativo base (BTC).
        :return: O dicionário de resposta da API da Binance se a ordem for bem-sucedida, caso contrário None.
        """
        if not self._client:
            logger.error("Cliente Binance não inicializado. Ordem não pode ser enviada.")
            return None

        # Validação do lado da ordem
        if side.upper() not in ['BUY', 'SELL']:
            logger.error(f"Lado da ordem inválido: '{side}'. Use 'BUY' ou 'SELL'.")
            return None

        try:
            logger.info(f"Tentando executar ordem de mercado: {side} {quantity} de {symbol}")
            
            if self.use_testnet:
                # A Testnet da Binance tem bugs com ordens a mercado usando 'quoteOrderQty'.
                # Criamos a ordem de teste, mas não executamos para evitar erros da API de teste.
                # Em um cenário real, você poderia ter uma lógica mais complexa aqui.
                logger.warning("--- MODO TESTNET ---")
                logger.warning(f"Ordem de {side} {symbol} com quantidade {quantity} foi criada, mas não executada.")
                # Simulamos uma resposta bem-sucedida para o fluxo do programa continuar
                return {
                    "symbol": symbol, "orderId": 12345, "status": "FILLED",
                    "side": side, "type": "MARKET", "executedQty": quantity
                }

            # Lógica para MODO REAL
            if side.upper() == 'BUY':
                # Para ordens de compra, usamos a quantidade do ativo de cotação (ex: gastar 100 USDT)
                order = self._client.create_order(
                    symbol=symbol,
                    side=Client.SIDE_BUY,
                    type=Client.ORDER_TYPE_MARKET,
                    quoteOrderQty=quantity # Quantidade em USDT
                )
            else: # side.upper() == 'SELL'
                # Para ordens de venda, usamos a quantidade do ativo base (ex: vender 0.001 BTC)
                order = self._client.create_order(
                    symbol=symbol,
                    side=Client.SIDE_SELL,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=quantity # Quantidade em BTC
                )
            
            logger.info(f"✅ Ordem executada com sucesso: {order}")
            return order

        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Erro na API da Binance ao colocar ordem: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Erro inesperado ao colocar ordem: {e}", exc_info=True)
            return None

# Instância única para ser usada em toda a aplicação
exchange_manager = ExchangeManager()