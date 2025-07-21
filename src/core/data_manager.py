# src/data_manager.py (VERSÃO 6.3 - SINAL MACRO E CORREÇÃO DE WARNING)

import os
import datetime
import time
import pandas as pd
import numpy as np
import yfinance as yf
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from tqdm import tqdm
from typing import Tuple, List

from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator, CCIIndicator
from ta.momentum import StochasticOscillator, RSIIndicator, WilliamsRIndicator

from src.logger import logger
from src.config import settings
from src.core.situational_awareness import SituationalAwareness

def _optimize_memory_usage(df: pd.DataFrame) -> pd.DataFrame:
    logger.debug("Otimizando uso de memória do DataFrame...")
    if 'market_regime' in df.columns:
        df['market_regime'] = df['market_regime'].astype('category')
    for col in df.columns:
        col_type = df[col].dtype
        if col_type != object and 'datetime' not in str(col_type) and 'category' not in str(col_type):
            c_min, c_max = df[col].min(), df[col].max()
            if str(col_type)[:3] == 'int':
                if c_min > np.iinfo(np.int8).min and c_max < np.iinfo(np.int8).max: df[col] = df[col].astype(np.int8)
                elif c_min > np.iinfo(np.int16).min and c_max < np.iinfo(np.int16).max: df[col] = df[col].astype(np.int16)
                elif c_min > np.iinfo(np.int32).min and c_max < np.iinfo(np.int32).max: df[col] = df[col].astype(np.int32)
                elif c_min > np.iinfo(np.int64).min and c_max < np.iinfo(np.int64).max: df[col] = df[col].astype(np.int64)
            else:
                if c_min > np.finfo(np.float32).min and c_max < np.finfo(np.float32).max: df[col] = df[col].astype(np.float32)
                else: df[col] = df[col].astype(np.float64)
    logger.debug("Otimização de memória concluída.")
    return df

from src.database import Database

from typing import Optional

class DataManager:
    """A class to manage the data for the trading bot."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        """
        Initializes the DataManager class.

        Args:
            db_url: The database URL. If not provided, it will be read from the DATABASE_URL environment variable.
        """
        self.db = Database(db_url)
        self.client = None
        if not settings.FORCE_OFFLINE_MODE:
            try:
                api_key_to_use = settings.BINANCE_TESTNET_API_KEY if settings.USE_TESTNET else settings.BINANCE_API_KEY
                api_secret_to_use = settings.BINANCE_TESTNET_API_SECRET if settings.USE_TESTNET else settings.BINANCE_API_SECRET

                if not api_key_to_use or not api_secret_to_use:
                    logger.warning("API Key ou Secret não encontradas para o modo selecionado. Operando em modo OFFLINE-FALLBACK.")
                    self.client = None
                    return

                self.client = Client(api_key_to_use, api_secret_to_use, tld='com', testnet=settings.USE_TESTNET, requests_params={"timeout": 20})
                self.client.ping()
                log_message = f"Cliente Binance inicializado em modo {'TESTNET' if settings.USE_TESTNET else 'REAL'}. Conexão com a API confirmada."
                logger.info(log_message)
            except (BinanceAPIException, BinanceRequestException, Exception) as e:
                logger.warning(f"FALHA NA CONEXÃO: {e}. O bot operará em modo OFFLINE-FALLBACK.")
                self.client = None
        else:
            logger.info("MODO OFFLINE FORÇADO está ativo.")

        self.situational_awareness = SituationalAwareness()
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

class DataManager:
    def __init__(self, db_url: Optional[str] = None) -> None:
        """
        Initializes the DataManager class.

        Args:
            db_url: The database URL. If not provided, it will be read from the DATABASE_URL environment variable.
        """
        self.db = Database(db_url)
        self.client = None
        if not settings.FORCE_OFFLINE_MODE:
            try:
                api_key_to_use = settings.BINANCE_TESTNET_API_KEY if settings.USE_TESTNET else settings.BINANCE_API_KEY
                api_secret_to_use = settings.BINANCE_TESTNET_API_SECRET if settings.USE_TESTNET else settings.BINANCE_API_SECRET

                if not api_key_to_use or not api_secret_to_use:
                    logger.warning("API Key ou Secret não encontradas para o modo selecionado. Operando em modo OFFLINE-FALLBACK.")
                    self.client = None
                    return

                self.client = Client(api_key_to_use, api_secret_to_use, tld='com', testnet=settings.USE_TESTNET, requests_params={"timeout": 20})
                self.client.ping()
                log_message = f"Cliente Binance inicializado em modo {'TESTNET' if settings.USE_TESTNET else 'REAL'}. Conexão com a API confirmada."
                logger.info(log_message)
            except (BinanceAPIException, BinanceRequestException, Exception) as e:
                logger.warning(f"FALHA NA CONEXÃO: {e}. O bot operará em modo OFFLINE-FALLBACK.")
                self.client = None
        else:
            logger.info("MODO OFFLINE FORÇADO está ativo.")
            
        self.situational_awareness = SituationalAwareness()
        self.feature_names = [
            'rsi', 'rsi_1h', 'rsi_4h', 'macd_diff', 'macd_diff_1h', 'stoch_osc', 'adx', 'adx_power',
            'atr', 'bb_width', 'bb_pband', 'sma_7_25_diff', 'close_sma_25_dist',
            'twitter_sentiment',
            'price_change_1m', 'price_change_5m', 'dxy_close_change', 'vix_close_change',
            'gold_close_change', 'tnx_close_change', 'atr_long_avg', 'volume_sma_50',
            'cci', 'williams_r', 'momentum_10m', 'volatility_ratio', 'sma_50_200_diff',
            'btc_dxy_corr_30d', 'btc_vix_corr_30d',
            'dxy_change_X_bull', 'dxy_change_X_bear', 'dxy_change_X_lateral',
            'market_situation'
        ]

    def _prepare_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Iniciando preparação de todas as features e indicadores técnicos...")
        epsilon = 1e-10
        
        # --- Indicadores Técnicos ---
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / (bb.bollinger_mavg() + epsilon)
        df['bb_pband'] = bb.bollinger_pband()
        sma_7 = df['close'].rolling(window=7).mean()
        sma_25 = df['close'].rolling(window=25).mean()
        sma_50 = df['close'].rolling(window=50).mean()
        sma_200 = df['close'].rolling(window=200).mean()
        df['sma_7_25_diff'] = (sma_7 - sma_25) / (df['close'] + epsilon)
        df['close_sma_25_dist'] = (df['close'] - sma_25) / (sma_25 + epsilon)
        df['macd_diff'] = MACD(close=df['close']).macd_diff()
        adx_indicator = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
        df['adx'] = adx_indicator.adx()
        df['adx_power'] = (adx_indicator.adx_pos() - adx_indicator.adx_neg())
        df['price_change_1m'] = df['close'].pct_change(1)
        df['price_change_5m'] = df['close'].pct_change(5)
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        df['stoch_osc'] = StochasticOscillator(high=df['high'], low=df['low'], close=df['close']).stoch()
        df['atr_long_avg'] = df['atr'].rolling(window=100).mean()
        df['volume_sma_50'] = df['volume'].rolling(window=50).mean()
        df['cci'] = CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()
        df['williams_r'] = WilliamsRIndicator(high=df['high'], low=df['low'], close=df['close'], lbp=14).williams_r()
        df['momentum_10m'] = df['close'].pct_change(10)
        atr_short = df['atr'].rolling(window=5).mean()
        df['volatility_ratio'] = atr_short / (df['atr_long_avg'] + epsilon)
        df['sma_50_200_diff'] = (sma_50 - sma_200) / (df['close'] + epsilon)

        # --- Features Macro ---
        macro_map = {'dxy_close': 'dxy_close_change', 'vix_close': 'vix_close_change', 'gold_close': 'gold_close_change', 'tnx_close': 'tnx_close_change'}
        for col_in, col_out in macro_map.items():
            df[col_out] = df[col_in].pct_change(1440).fillna(0) if col_in in df.columns else 0.0

        # --- Suíte de Features de Correlação Macro ---
        logger.debug("Calculando suíte de correlações macro (BTC vs DXY, BTC vs VIX)...")
        macro_corr_assets = {'dxy': 'dxy_close', 'vix': 'vix_close'}
        for asset_name, asset_col in macro_corr_assets.items():
            feature_name = f'btc_{asset_name}_corr_30d'
            if asset_col in df.columns:
                df_daily_btc = df['close'].resample('D').last()
                df_daily_asset = df[asset_col].resample('D').last()
                btc_returns = df_daily_btc.pct_change()
                asset_returns = df_daily_asset.pct_change()
                rolling_corr = btc_returns.rolling(window=30).corr(asset_returns)
                df[feature_name] = rolling_corr.reindex(df.index, method='ffill')
                
                # === CORREÇÃO DO FUTUREWARNING ===
                # Substituímos .bfill(inplace=True) pela forma recomendada
                df[feature_name] = df[feature_name].bfill()
            else:
                df[feature_name] = 0.0

        # --- Features Multi-Timeframe ---
        df_1h = df['close'].resample('h').last()
        df['rsi_1h'] = RSIIndicator(close=df_1h, window=14).rsi().reindex(df.index, method='ffill')
        df['macd_diff_1h'] = MACD(close=df_1h).macd_diff().reindex(df.index, method='ffill')
        df_4h = df['close'].resample('4h').last()
        df['rsi_4h'] = RSIIndicator(close=df_4h, window=14).rsi().reindex(df.index, method='ffill')
        for col in ['rsi_1h', 'macd_diff_1h', 'rsi_4h']:
            df[col] = df[col].bfill().ffill()

        logger.debug("Cálculo bruto das features concluído.")
        return df
        
    def _add_market_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Calculando regimes de mercado (Camada 2: Tendência + Volatilidade)...")
        if df.empty or 'close' not in df.columns or 'atr' not in df.columns:
            logger.warning("DataFrame vazio ou sem colunas 'close'/'atr'. Não é possível calcular regimes.")
            df['market_regime'] = 'INDETERMINADO'
            return df

        df_daily = df['close'].resample('D').last()
        sma_50d = df_daily.rolling(window=50).mean()
        sma_200d = df_daily.rolling(window=200).mean()
        trend_conditions = [(df_daily > sma_50d) & (sma_50d > sma_200d), (df_daily > sma_200d) & (df_daily < sma_50d), (df_daily < sma_200d)]
        trend_outcomes = ['BULL_FORTE', 'RECUPERACAO', 'BEAR']
        regime_trend = np.select(trend_conditions, trend_outcomes, default='LATERAL')
        regime_trend = pd.Series(regime_trend, index=df_daily.index)
        atr_daily = df['atr'].resample('D').mean()
        atr_sma_50 = atr_daily.rolling(window=50).mean()
        volatility_regime = np.where(atr_daily > atr_sma_50, '_VOLATIL', '_CALMO')
        volatility_regime = pd.Series(volatility_regime, index=atr_daily.index)
        combined_regime = regime_trend + volatility_regime
        df['market_regime'] = combined_regime.reindex(df.index, method='ffill')
        # === CORREÇÃO DO FUTUREWARNING ===
        df['market_regime'] = df['market_regime'].bfill()
        logger.debug("Regimes de mercado calculados.")
        return df
    
    # ... (O restante do arquivo permanece idêntico) ...
    def _fetch_and_update_macro_data(self) -> None:
        """Fetches and updates the macro data from Yahoo Finance."""
        if not self.client:
            logger.debug("Modo offline. Pulando atualização de dados macro.")
            return

        logger.info("Iniciando verificação e atualização dos dados macro...")
        ticker_map = {'dxy': 'DX-Y.NYB', 'gold': 'GC=F', 'tnx': '^TNX', 'vix': '^VIX'}

        for nome_ativo, ticker in ticker_map.items():
            table_name = f"macro_{nome_ativo}"
            try:
                self.db.create_table(table_name, [
                    "Date TIMESTAMP",
                    "Open FLOAT",
                    "High FLOAT",
                    "Low FLOAT",
                    "Close FLOAT",
                    "Volume FLOAT"
                ])

                last_date_query = f"SELECT MAX(Date) FROM {table_name}"
                last_date_result = self.db.execute_query(last_date_query).scalar()
                start_fetch_date = '2017-01-01'
                if last_date_result:
                    start_fetch_date = last_date_result + datetime.timedelta(days=1)

                end_fetch_date = datetime.datetime.now(datetime.timezone.utc)
                if isinstance(start_fetch_date, (datetime.datetime, pd.Timestamp)) and start_fetch_date.date() >= end_fetch_date.date():
                    logger.info(f"Dados macro para '{nome_ativo}' já estão atualizados.")
                    continue
                
                logger.debug(f"Baixando dados para '{nome_ativo}' de {start_fetch_date if isinstance(start_fetch_date, str) else start_fetch_date.strftime('%Y-%m-%d')} até hoje...")
                df_downloaded = yf.download(ticker, start=start_fetch_date, end=end_fetch_date, progress=False, auto_adjust=True)
                
                if df_downloaded.empty:
                    logger.debug(f"Nenhum dado novo encontrado para '{nome_ativo}'.")
                    continue
                
                clean_df = df_downloaded[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                clean_df.index.name = 'Date'
                
                self.db.insert_dataframe(clean_df.reset_index(), table_name, if_exists='append')
                time.sleep(1) 
            except Exception as e:
                logger.error(f"Falha ao buscar ou salvar dados para o ativo '{nome_ativo}': {e}", exc_info=True)
        logger.debug("Verificação de dados macro concluída.")

    def _load_and_unify_local_macro_data(self) -> pd.DataFrame:
        """Loads and unifies the local macro data from the database."""
        logger.debug("Padronizando e unificando dados macro do banco de dados...")
        nomes_ativos = ['dxy', 'gold', 'tnx', 'vix']
        lista_dataframes = []
        for nome_ativo in nomes_ativos:
            table_name = f"macro_{nome_ativo}"
            try:
                query = f"SELECT Date, Close FROM {table_name}"
                df = self.db.fetch_data(query)
                if df.empty:
                    logger.warning(f"AVISO: Nenhum dado encontrado na tabela '{table_name}'. Pulando.")
                    continue
                df.set_index('Date', inplace=True)
                if df.index.tz is None: df.index = df.index.tz_localize('UTC')
                else: df.index = df.index.tz_convert('UTC')
                df.rename(columns={'Close': f'{nome_ativo}_close'}, inplace=True)
                lista_dataframes.append(df)
            except Exception as e:
                logger.error(f"ERRO ao processar a tabela macro '{table_name}': {e}", exc_info=True)
        if not lista_dataframes:
            logger.warning("Nenhum dado macro foi processado.")
            return pd.DataFrame()
        df_final = pd.concat(lista_dataframes, axis=1, join='outer')
        df_final.sort_index(inplace=True); df_final.ffill(inplace=True); df_final.dropna(how='all', inplace=True)
        logger.debug("Dados macro do banco de dados unificados com sucesso.")
        return df_final
    
    def _fetch_and_update_twitter_sentiment(self) -> None:
        """Fetches and updates the twitter sentiment from a specific user."""
        if not self.client:
            logger.debug("Modo offline. Pulando atualização de dados do Twitter.")
            return

        logger.info("Iniciando verificação e atualização do sentimento do Twitter...")
        analyzer = SentimentIntensityAnalyzer()

        # This is a placeholder for fetching tweets. In a real-world scenario, you would use the Twitter API to fetch the tweets.
        tweets = [
            "I love #Bitcoin!",
            "I hate #Bitcoin!",
            "I'm neutral on #Bitcoin.",
        ]

        sentiments = [analyzer.polarity_scores(tweet)['compound'] for tweet in tweets]
        avg_sentiment = np.mean(sentiments)

        table_name = "twitter_sentiment"
        self.db.create_table(table_name, [
            "timestamp TIMESTAMP",
            "sentiment FLOAT"
        ])

        df = pd.DataFrame([{'timestamp': datetime.datetime.now(datetime.timezone.utc), 'sentiment': avg_sentiment}])
        self.db.insert_dataframe(df, table_name, if_exists='append')
        logger.debug("Verificação do sentimento do Twitter concluída.")

    def get_historical_data_by_batch(self, symbol: str, interval: str, start_date_dt: datetime.datetime, end_date_dt: datetime.datetime) -> pd.DataFrame:
        """
        Fetches historical data from Binance in batches.

        Args:
            symbol: The symbol to fetch the data for.
            interval: The interval of the data.
            start_date_dt: The start date of the data.
            end_date_dt: The end date of the data.

        Returns:
            A pandas DataFrame with the historical data.
        """
        all_dfs = []
        total_days = max(1, (end_date_dt - start_date_dt).days)
        progress_bar = tqdm(total=total_days, desc=f"Baixando dados de {symbol}", unit="d", leave=False, disable=False)
        cursor = start_date_dt
        while cursor < end_date_dt:
            chunk_size_days = 30
            next_cursor = min(cursor + datetime.timedelta(days=chunk_size_days), end_date_dt)
            start_str, end_str = cursor.strftime("%Y-%m-%d %H:%M:%S"), next_cursor.strftime("%Y-%m-%d %H:%M:%S")
            klines = self.client.get_historical_klines(symbol, interval, start_str, end_str)
            if not klines:
                days_processed = (next_cursor - cursor).days; progress_bar.update(days_processed if days_processed > 0 else 1)
                cursor = next_cursor
                continue
            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','qav','nt','tbbav','tbqav','ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms'); df.set_index('timestamp', inplace=True); df.index = df.index.tz_localize('UTC')
            df = df[['open','high','low','close','volume']].astype(float)
            all_dfs.append(df)
            days_processed = (next_cursor - cursor).days; progress_bar.update(days_processed if days_processed > 0 else 1)
            cursor = next_cursor; time.sleep(0.2)
        progress_bar.close()
        return pd.concat(all_dfs) if all_dfs else pd.DataFrame()

    def _fetch_and_manage_btc_data(self, symbol: str, interval: str = '1m') -> pd.DataFrame:
        """
        Fetches and manages the BTC data.

        Args:
            symbol: The symbol to fetch the data for.
            interval: The interval of the data.

        Returns:
            A pandas DataFrame with the BTC data.
        """
        table_name = f"btc_{symbol.lower()}_{interval}"
        self.db.create_table(table_name, [
            "timestamp TIMESTAMP",
            "open FLOAT",
            "high FLOAT",
            "low FLOAT",
            "close FLOAT",
            "volume FLOAT"
        ])

        end_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
        
        last_timestamp_query = f"SELECT MAX(timestamp) FROM {table_name}"
        last_timestamp_result = self.db.execute_query(last_timestamp_query).scalar()

        if last_timestamp_result:
            df = self.db.fetch_data(f"SELECT * FROM {table_name}")
            df.set_index('timestamp', inplace=True)
            df.index = pd.to_datetime(df.index, utc=True)
            
            if self.client:
                last_timestamp = df.index.max().to_pydatetime()
                if last_timestamp < end_utc:
                    logger.info("Dados do BTC no banco de dados estão desatualizados. Buscando novos dados da Binance...")
                    try:
                        df_new = self.get_historical_data_by_batch(symbol, interval, last_timestamp + datetime.timedelta(minutes=1), end_utc)
                        if not df_new.empty:
                            self.db.insert_dataframe(df_new.reset_index(), table_name, if_exists='append')
                            df = pd.concat([df, df_new]); df = df.loc[~df.index.duplicated(keep='last')]; df.sort_index(inplace=True)
                            logger.info(f"SUCESSO: Banco de dados do BTC atualizado com {len(df_new)} novas velas.")
                    except Exception as e: logger.warning(f"FALHA NA ATUALIZAÇÃO DO BTC: {e}. Continuando com dados do banco de dados.")
            return df

        if os.path.exists(settings.KAGGLE_BOOTSTRAP_FILE):
            logger.info(f"Nenhum dado no banco de dados. Iniciando a partir do arquivo Kaggle: '{settings.KAGGLE_BOOTSTRAP_FILE}'")
            df_kaggle = pd.read_csv(settings.KAGGLE_BOOTSTRAP_FILE, low_memory=False, on_bad_lines='skip')
            df = self._preprocess_kaggle_data(df_kaggle)
            self.db.insert_dataframe(df.reset_index(), table_name, if_exists='replace')
            return df

        if self.client:
            logger.warning("Nenhum arquivo local do BTC encontrado. Baixando o último ano da Binance como fallback.")
            start_utc = end_utc - datetime.timedelta(days=365); df = self.get_historical_data_by_batch(symbol, interval, start_utc, end_utc)
            if not df.empty:
                self.db.insert_dataframe(df.reset_index(), table_name, if_exists='replace')
            return df

        logger.error("Nenhum arquivo de dados local do BTC encontrado e o bot está em modo offline. Não é possível continuar.")
        return pd.DataFrame()
        
    def _preprocess_kaggle_data(self, df_kaggle: pd.DataFrame) -> pd.DataFrame:
        """
        Preprocesses the Kaggle data.

        Args:
            df_kaggle: The Kaggle DataFrame to preprocess.

        Returns:
            A preprocessed pandas DataFrame.
        """
        logger.debug("Pré-processando dados do Kaggle...")
        column_mapping = {'Timestamp': 'timestamp', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}
        possible_volume_names = ['Volume_(BTC)', 'Volume', 'Volume (BTC)', 'Volume (Currency)', 'Volume USD']
        found_volume_col = next((name for name in possible_volume_names if name in df_kaggle.columns), None)
        if not found_volume_col: raise ValueError(f"Não foi possível encontrar uma coluna de volume no arquivo Kaggle.")
        column_mapping[found_volume_col] = 'volume'
        df_kaggle.rename(columns=column_mapping, inplace=True)
        df_kaggle['timestamp'] = pd.to_datetime(df_kaggle['timestamp'], unit='s')
        df_kaggle.set_index('timestamp', inplace=True)
        df_kaggle.index = df_kaggle.index.tz_localize('UTC')
        final_columns = ['open', 'high', 'low', 'close', 'volume']
        df = df_kaggle[final_columns].copy()
        df.dropna(inplace=True)
        df = df.astype(float)
        logger.debug(f"Processamento do Kaggle concluído. {len(df)} registros válidos carregados.")
        return df

    def update_and_load_data(self, symbol: str, interval: str = '1m') -> pd.DataFrame:
        """
        Updates and loads the data.

        Args:
            symbol: The symbol to fetch the data for.
            interval: The interval of the data.

        Returns:
            A pandas DataFrame with the updated and loaded data.
        """
        logger.info("Iniciando processo de unificação de dados.")
        
        self._fetch_and_update_macro_data()
        self._fetch_and_update_twitter_sentiment()
        df_btc = self._fetch_and_manage_btc_data(symbol, interval)
        if df_btc.empty: return pd.DataFrame()

        df_macro = self._load_and_unify_local_macro_data()
        df_sentiment = self.db.fetch_data("SELECT * FROM twitter_sentiment")
        df_sentiment.set_index('timestamp', inplace=True)
        df_sentiment.index = pd.to_datetime(df_sentiment.index, utc=True)

        if not df_macro.empty:
            df_combined = df_btc.join(df_macro, how='left')
        else:
            df_combined = df_btc

        if not df_sentiment.empty:
            df_combined = df_combined.join(df_sentiment, how='left')
            macro_cols = [col for col in df_combined.columns if '_close' in col]
            df_combined[macro_cols] = df_combined[macro_cols].ffill()
        else:
            df_combined = df_btc

        df_with_features = self._prepare_all_features(df_combined)
        df_with_regimes = self._add_market_regime(df_with_features)
        df_with_situations = self.situational_awareness.cluster_data(df_with_regimes)

        logger.info("Calculando features de interação (Camada 3: Tática Avançada)...")
        if 'dxy_close_change' in df_with_situations.columns:
            df_with_situations['dxy_change_X_bull'] = df_with_situations['dxy_close_change'] * df_with_situations['market_regime'].str.contains('BULL').astype(int)
            df_with_situations['dxy_change_X_bear'] = df_with_situations['dxy_close_change'] * df_with_situations['market_regime'].str.contains('BEAR').astype(int)
            df_with_situations['dxy_change_X_lateral'] = df_with_situations['dxy_close_change'] * df_with_situations['market_regime'].str.contains('LATERAL').astype(int)
        else:
            df_with_situations['dxy_change_X_bull'] = 0.0
            df_with_situations['dxy_change_X_bear'] = 0.0
            df_with_situations['dxy_change_X_lateral'] = 0.0

        logger.info("Filtrando dados de 2017 em diante e tratando valores ausentes/infinitos...")
        df_filtered = df_with_situations[df_with_situations.index >= '2017-01-01'].copy()
        
        logger.info("Aplicando shift(1) nas features para evitar lookahead bias...")
        df_filtered[self.feature_names] = df_filtered[self.feature_names].shift(1)
        
        df_filtered.replace([np.inf, -np.inf], np.nan, inplace=True)
        df_filtered.dropna(inplace=True)
        
        df_final = _optimize_memory_usage(df_filtered)
        
        logger.info("Processo de coleta e preparação de dados concluído com sucesso.")
        return df_final