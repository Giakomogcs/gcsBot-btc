# jules_bot/bot/live_feature_calculator.py (VERSÃO CORRIGIDA)

import pandas as pd
import requests
from datetime import datetime, timedelta

from jules_bot.utils.logger import logger
# --- IMPORTAÇÃO CORRIGIDA ---
from jules_bot.utils.config_manager import config_manager
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.database.data_manager import DataManager
from jules_bot.research.feature_engineering import add_all_features

class LiveFeatureCalculator:
    """
    Responsável por buscar todos os dados brutos necessários em tempo real,
    combiná-los e calcular o conjunto completo de features para a tomada de decisão.
    """
    def __init__(self, data_manager: DataManager, mode: str = 'trade'):
        self.data_manager = data_manager
        self.mode = mode
        self.exchange_manager = ExchangeManager(mode=self.mode)
        self.symbol = config_manager.get('APP', 'symbol')

    def _get_live_sentiment_data(self) -> pd.DataFrame:
        """Busca o dado mais recente de Fear & Greed."""
        try:
            url = "https://api.alternative.me/fng/?limit=1&format=json"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json().get('data')
            if not data: return pd.DataFrame()

            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(pd.to_numeric(df['timestamp']), unit='s', utc=True)
            df = df.rename(columns={'value': 'fear_and_greed'})
            df = df.set_index('timestamp')[['fear_and_greed']]
            df['fear_and_greed'] = pd.to_numeric(df['fear_and_greed'])
            return df
        except Exception as e:
            logger.warning(f"Não foi possível buscar dados de sentimento ao vivo: {e}")
            return pd.DataFrame()

    def get_current_candle_with_features(self) -> pd.Series:
        """
        Orquestra a busca de todos os dados, o cálculo de features e retorna
        a vela (Series) mais recente e completa para a tomada de decisão.
        """
        logger.debug("Iniciando cálculo de features em tempo real...")
        
        # 1. Dados de Velas (OHLCV) da Binance (base principal)
        df_candles = self.exchange_manager.get_historical_candles(self.symbol, '1m', limit=2*1440)
        if df_candles.empty:
            logger.error("Falha ao obter velas históricas da Binance. Abortando ciclo.")
            return pd.Series(dtype=float)

        # 2. Dados Macro e de Sentimento (Apenas para modo 'trade')
        if self.mode == 'trade':
            df_macro = self.data_manager.read_data_from_influx("macro_data_1m", start_date="-3d")
            
            df_sentiment_live = self._get_live_sentiment_data()
            df_sentiment_db = self.data_manager.read_data_from_influx("sentiment_fear_and_greed", start_date="-3d")
            
            if df_sentiment_db.empty and df_sentiment_live.empty:
                df_sentiment = pd.DataFrame()
            else:
                df_sentiment = pd.concat([df_sentiment_db, df_sentiment_live]).drop_duplicates()
        else:
            # Em modo 'test', não usamos esses dados
            df_macro = pd.DataFrame()
            df_sentiment = pd.DataFrame()


        # 4. Combinar todas as fontes de dados
        df_combined = df_candles.join(df_macro, how='left')
        if not df_sentiment.empty:
             df_combined = df_combined.join(df_sentiment, how='left')

        df_combined.ffill(inplace=True) # Preenche lacunas com o último valor válido

        # Adicionado para garantir que nenhum NaN passe para a engenharia de features
        if df_combined.isnull().values.any():
            logger.warning("NaNs encontrados após o ffill (provavelmente no início do histórico). Preenchendo com 0.")
            df_combined.fillna(0, inplace=True)

        # 5. Calcular todas as features usando a função centralizada
        # O modo 'trade' é o único modo verdadeiramente "live"
        is_live_mode = self.mode == 'trade'
        df_with_features = add_all_features(df_combined, live_mode=is_live_mode)
        
        if df_with_features.empty:
            logger.error("O DataFrame ficou vazio após o cálculo de features. Abortando ciclo.")
            return pd.Series(dtype=float)

        # 6. Obter o preço mais recente e preparar a vela final
        current_price = self.exchange_manager.get_current_price(self.symbol)
        if current_price is None:
            logger.error("Não foi possível obter o preço atual da corretora. Abortando ciclo.")
            return pd.Series(dtype=float)
        
        final_candle = df_with_features.iloc[-1].copy()
        final_candle['close'] = current_price
        final_candle.name = datetime.now(pd.Timestamp.utcnow().tz)

        logger.debug(f"Vela final gerada com {len(final_candle)} features.")
        return final_candle
