# jules_bot/bot/live_feature_calculator.py (VERSÃO CORRIGIDA)

import pandas as pd
import requests
from datetime import datetime, timedelta

from jules_bot.utils.logger import logger
# --- IMPORTAÇÃO CORRIGIDA ---
from jules_bot.utils.config_manager import config_manager
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.research.feature_engineering import add_all_features

class LiveFeatureCalculator:
    """
    Responsável por buscar todos os dados brutos necessários em tempo real,
    combiná-los e calcular o conjunto completo de features para a tomada de decisão.
    """
    def __init__(self, db_manager: PostgresManager, mode: str = 'trade'):
        self.db_manager = db_manager
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

    def get_features_dataframe(self) -> pd.DataFrame:
        """
        Orchestrates the fetching of all data, calculation of features, and returns
        the complete, recent DataFrame.
        """
        logger.debug("Iniciando cálculo de features em tempo real...")
        
        # 1. Dados de Velas (OHLCV) da Binance (base principal)
        # Aumentar o limite para garantir que a janela rolante do SA tenha dados suficientes (e.g., 72 períodos)
        df_candles = self.exchange_manager.get_historical_candles(self.symbol, '1m', limit=500)
        if df_candles.empty:
            logger.error("Falha ao obter velas históricas da Binance. Abortando ciclo.")
            return pd.DataFrame()

        # 2. Dados Macro e de Sentimento (Apenas para modo 'trade')
        if self.mode == 'trade':
            df_macro = self.db_manager.get_price_data("macro_data_1m", start_date="-3d")
            df_sentiment_live = self._get_live_sentiment_data()
            df_sentiment_db = self.db_manager.get_price_data("sentiment_fear_and_greed", start_date="-3d")
            df_sentiment = pd.concat([df_sentiment_db, df_sentiment_live]).drop_duplicates() if not (df_sentiment_db.empty and df_sentiment_live.empty) else pd.DataFrame()
        else:
            df_macro = pd.DataFrame()
            df_sentiment = pd.DataFrame()

        # 4. Combinar todas as fontes de dados
        # Adicionado rsuffix para evitar erro de colunas sobrepostas com df_macro
        df_combined = df_candles.join(df_macro, how='left', rsuffix='_macro')
        if not df_sentiment.empty:
             df_combined = df_combined.join(df_sentiment, how='left', rsuffix='_sentiment')

        df_combined.ffill(inplace=True)
        if df_combined.isnull().values.any():
            logger.warning("NaNs encontrados após o ffill. Preenchendo com 0.")
            df_combined.fillna(0, inplace=True)

        # 5. Calcular todas as features
        is_live_mode = self.mode == 'trade'
        df_with_features = add_all_features(df_combined, live_mode=is_live_mode)
        
        if df_with_features.empty:
            logger.error("O DataFrame ficou vazio após o cálculo de features.")
            return pd.DataFrame()

        # 6. Atualizar o preço de fechamento da última vela com o preço de ticker mais recente
        current_price = self.exchange_manager.get_current_price(self.symbol)
        if current_price is not None:
            df_with_features.iloc[-1, df_with_features.columns.get_loc('close')] = current_price
        else:
            logger.warning("Não foi possível obter o preço atual; o último preço de 'close' será da última vela.")

        return df_with_features

    def get_current_candle_with_features(self) -> pd.Series:
        """
        Retorna apenas a vela (Series) mais recente com todas as features.
        Este é um wrapper de conveniência em torno do get_features_dataframe().
        """
        df_with_features = self.get_features_dataframe()
        if df_with_features.empty:
            return pd.Series(dtype=float)
        
        final_candle = df_with_features.iloc[-1].copy()
        final_candle.name = datetime.now(pd.Timestamp.utcnow().tz)

        logger.debug(f"Vela final gerada com {len(final_candle)} features.")
        return final_candle

    def get_historical_data_with_features(self) -> pd.DataFrame:
        """
        Busca um histórico de dados de velas e calcula todas as features,
        retornando um DataFrame completo para o treinamento de modelos.
        """
        logger.debug("Buscando dados históricos para cálculo de features...")

        # Busca um histórico maior para garantir que os indicadores (ex: médias móveis longas) sejam calculados corretamente
        df_candles = self.exchange_manager.get_historical_candles(self.symbol, '1m', limit=5000)
        if df_candles.empty:
            logger.error("Falha ao obter velas históricas da Binance para o treinamento do SA.")
            return pd.DataFrame()

        # Para dados históricos, não precisamos de dados macro ou de sentimento em tempo real
        # A função add_all_features já lida com a ausência dessas colunas

        # O modo 'live' deve ser False, pois estamos lidando com um conjunto de dados históricos
        df_with_features = add_all_features(df_candles, live_mode=False)

        # Remove quaisquer linhas com NaNs que possam ter sido geradas no início do histórico
        df_with_features.dropna(inplace=True)

        logger.debug(f"DataFrame histórico com features gerado. Shape: {df_with_features.shape}")
        return df_with_features
