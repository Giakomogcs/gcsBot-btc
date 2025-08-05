# Ficheiro: src/core/exchange_manager.py (VERSÃO FINAL COM CORREÇÃO DE TIMEZONE)

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from gcs_bot.utils.config_manager import settings
from gcs_bot.utils.logger import logger
from typing import Optional, Union
import pandas as pd

class ExchangeManager:
    """
    Classe responsável por toda a comunicação com a API da corretora (Binance).
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
        """Busca o saldo livre de um ativo específico na conta da corretora."""
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Retornando saldo 0.")
            return 0.0
        try:
            balance_info = self._client.get_asset_balance(asset=asset)
            if balance_info:
                return float(balance_info['free'])
            return 0.0
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar saldo: {e}", exc_info=True)
            return 0.0

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Busca o preço de mercado mais recente para um par de negociação."""
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Não é possível buscar o preço.")
            return None
        try:
            ticker = self._client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar preço: {e}", exc_info=True)
            return None

    def get_historical_candles(self, symbol: str, interval: str = '1m', limit: int = 100) -> pd.DataFrame:
        """
        Busca as últimas N velas (candles) para um símbolo, garantindo que o
        fuso horário (timezone) UTC seja definido.
        """
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Não é possível buscar velas históricas.")
            return pd.DataFrame()
        try:
            klines = self._client.get_klines(symbol=symbol, interval=interval, limit=limit)
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume', 
                'close_time', 'quote_asset_volume', 'number_of_trades', 
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # --- LINHA CORRIGIDA ---
            # Adicionamos utc=True para criar um DatetimeIndex "timezone-aware".
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            
            df.set_index('timestamp', inplace=True)
            
            ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
            df = df[ohlcv_cols]
            df = df.astype(float)
            
            return df
            
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar velas: {e}", exc_info=True)
            return pd.DataFrame()

    def place_market_order(self, symbol: str, side: str, quantity: Union[float, str]) -> Optional[dict]:
        """Envia uma ordem de mercado para a corretora."""
        if not self._client:
            logger.error("Cliente Binance não inicializado. Ordem não pode ser enviada.")
            return None
        if side.upper() not in ['BUY', 'SELL']:
            logger.error(f"Lado da ordem inválido: '{side}'. Use 'BUY' ou 'SELL'.")
            return None
        try:
            logger.info(f"TENTANDO EXECUTAR ORDEM DE MERCADO: {side} {quantity} de {symbol}")
            if side.upper() == 'BUY':
                order = self._client.create_order(
                    symbol=symbol, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=quantity
                )
            else:
                order = self._client.create_order(
                    symbol=symbol, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=quantity
                )
            logger.info(f"✅ ORDEM EXECUTADA COM SUCESSO: {order}")
            return order
        except Exception as e:
            logger.error(f"ERRO INESPERADO AO COLOCAR ORDEM: {e}", exc_info=True)
            return None

exchange_manager = ExchangeManager()