# Ficheiro: src/core/exchange_manager.py (VERSÃO FINAL COM CORREÇÃO DE TIMEZONE)

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from typing import Optional, Union
import pandas as pd
import time
from datetime import datetime, timedelta

class ExchangeManager:
    """
    Classe responsável por toda a comunicação com a API da corretora (Binance).
    """
    def __init__(self, mode: str = 'trade'):
        self.mode = mode
        self._client = self._init_binance_client()

    def _init_binance_client(self) -> Optional[Client]:
        """Inicializa e autentica o cliente da API da Binance com base no modo."""
        if self.mode == 'offline':
            logger.warning("Modo OFFLINE. ExchangeManager não se conectará.")
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

            # Sincroniza o tempo com o servidor da Binance para evitar erros de timestamp
            try:
                server_time = client.get_server_time()
                local_time = int(time.time() * 1000)
                time_diff = server_time['serverTime'] - local_time
                client.timestamp_offset = time_diff
                logger.info(f"Offset de tempo com o servidor da Binance ajustado em {time_diff} ms.")
            except Exception as e:
                logger.error(f"Não foi possível sincronizar o tempo com a Binance. Erro: {e}", exc_info=True)
                # Mesmo que a sincronização falhe, tentamos continuar.
                # O erro de timestamp pode ocorrer mais tarde.

            client.ping()
            logger.info(f"✅ Conexão com a Binance estabelecida com sucesso (Modo: {'TESTNET' if use_testnet else 'REAL'}).")
            return client
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"❌ Falha na conexão com a Binance: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ Ocorreu um erro inesperado ao inicializar o cliente Binance: {e}", exc_info=True)
            return None

    def close_connection(self):
        """Closes the connection to the exchange."""
        if self._client:
            self._client.close_connection()
            logger.info("Conexão com a Binance fechada.")

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

    def get_historical_candles_long_period(self, symbol: str, interval: str, start_str: str) -> pd.DataFrame:
        """
        Busca velas históricas para um período longo, usando o gerador da biblioteca.
        """
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Não é possível buscar velas históricas.")
            return pd.DataFrame()

        try:
            logger.info(f"Iniciando busca de velas históricas para {symbol} desde {start_str}...")

            klines_generator = self._client.get_historical_klines_generator(symbol, interval, start_str)
            klines = list(klines_generator)

            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])

            if df.empty:
                logger.warning("Nenhuma vela histórica encontrada para o período.")
                return pd.DataFrame()

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)

            ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
            df = df[ohlcv_cols]
            df = df.astype(float)

            logger.info(f"✅ {len(df)} velas históricas para {symbol} foram baixadas com sucesso.")
            return df

        except Exception as e:
            logger.error(f"Erro inesperado ao buscar velas históricas de longo período: {e}", exc_info=True)
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

    def get_all_open_positions_from_exchange(self) -> list:
        """
        Fetches the current balance of the base asset to represent the open position.
        In spot trading, the 'position' is just the amount of the asset you hold.
        """
        if not self._client:
            logger.warning("Cliente Binance não inicializado. Não é possível buscar posições.")
            return []

        try:
            account_info = self._client.get_account()
            # Find the balance for the base asset (e.g., BTC)
            symbol = config_manager.get('APP', 'symbol')
            base_asset = symbol.replace("USDT", "") # A bit simplistic, assumes USDT quote

            positions = []
            for balance in account_info['balances']:
                if balance['asset'] == base_asset and float(balance['free']) > 0:
                    positions.append({
                        "symbol": symbol,
                        "quantity": float(balance['free']),
                        "side": "BUY" # Implied, as we are holding it
                    })
            return positions
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar posições abertas na exchange: {e}", exc_info=True)
            return []