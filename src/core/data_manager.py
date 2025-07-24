# src/data_manager.py (VERSÃO COM ORDER FLOW)

import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


import time

import datetime
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from tqdm import tqdm
from typing import Optional

from src.logger import logger
from src.config_manager import settings
from src.database_manager import db_manager
from src.core.situational_awareness import SituationalAwareness

class DataManager:
    """
    Gerencia a coleta, processamento, armazenamento e leitura de todos os dados do mercado,
    incluindo dados de velas (OHLCV) e de fluxo de ordens (Order Flow).
    """
    def __init__(self) -> None:
        # ... (o __init__ continua exatamente igual)
        self.client = None
        self.binance_client_init()
        self.situational_awareness = SituationalAwareness()
        self.feature_names = [
            'rsi', 'rsi_1h', 'rsi_4h', 'macd_diff', 'macd_diff_1h', 'macd_diff_4h', 'stoch_osc', 'adx', 'adx_power',
            'atr', 'bb_width', 'bb_pband', 'sma_7_25_diff', 'close_sma_25_dist',
            'twitter_sentiment', 
            'price_change_1m', 'price_change_5m', 'dxy_close_change', 'vix_close_change',
            'gold_close_change', 'tnx_close_change', 'atr_long_avg', 'volume_sma_50',
            'cci', 'williams_r', 'momentum_10m', 'volatility_ratio', 'sma_50_200_diff',
            'btc_dxy_corr_30d', 'btc_vix_corr_30d',
            'dxy_change_X_bull', 'dxy_change_X_bear', 'dxy_change_X_lateral',
            'market_situation'
        ]

    # ... (binance_client_init, _write_dataframe_to_influx, _query_last_timestamp, read_data_from_influx continuam iguais)
    def binance_client_init(self) -> None:
        if settings.app.force_offline_mode:
            logger.info("MODO OFFLINE FORÇADO está ativo.")
            self.client = None
            return
        try:
            api_key = settings.binance_testnet_api_key if settings.app.use_testnet else settings.binance_api_key
            api_secret = settings.binance_testnet_api_secret if settings.app.use_testnet else settings.binance_api_secret
            if not api_key or not api_secret:
                logger.warning("API Key/Secret não encontradas. Operando em modo OFFLINE-FALLBACK.")
                self.client = None
                return
            self.client = Client(api_key, api_secret, tld='com', testnet=settings.app.use_testnet)
            self.client.ping()
            mode = "TESTNET" if settings.app.use_testnet else "REAL"
            logger.info(f"✅ Cliente Binance inicializado em modo {mode}.")
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            logger.warning(f"❌ FALHA NA CONEXÃO com a Binance: {e}.")
            self.client = None
    
    def _write_dataframe_to_influx(self, df: pd.DataFrame, measurement: str, tag_columns: list = [], batch_size: int = 5_000):
        write_api = db_manager.get_write_api()
        if not write_api:
            logger.error(f"API de escrita do InfluxDB indisponível. Escrita para '{measurement}' abortada.")
            return
        df_to_write = df.reset_index()
        total_rows = len(df_to_write)
        if total_rows == 0:
            logger.info(f"Nenhum dado novo para escrever em '{measurement}'.")
            return
        num_batches = (total_rows // batch_size) + (1 if total_rows % batch_size > 0 else 0)
        logger.info(f"Escrevendo {total_rows} registos para '{measurement}' em {num_batches} lotes...")
        try:
            for i in tqdm(range(0, total_rows, batch_size), desc=f"Writing to {measurement}"):
                batch = df_to_write.iloc[i:i + batch_size]
                write_api.write(
                    bucket=settings.influxdb_bucket,
                    record=batch,
                    data_frame_measurement_name=measurement,
                    data_frame_tag_columns=tag_columns,
                    data_frame_timestamp_column="timestamp"
                )
            logger.info(f"✅ Escrita para '{measurement}' concluída com sucesso.")
        except Exception as e:
            logger.error(f"❌ Erro ao escrever dados para o InfluxDB: {e}", exc_info=True)

    def _query_last_timestamp(self, measurement: str) -> Optional[pd.Timestamp]:
        query_api = db_manager.get_query_api()
        if not query_api: return None
        query = f'from(bucket:"{settings.influxdb_bucket}") |> range(start: 0) |> filter(fn: (r) => r._measurement == "{measurement}") |> last() |> keep(columns: ["_time"])'
        try:
            result = query_api.query(query)
            if not result or not result[0].records: return None
            return pd.to_datetime(result[0].records[0].get_time()).tz_convert('UTC')
        except Exception as e:
            logger.error(f"Erro ao buscar o último timestamp do InfluxDB: {e}")
            return None

    def read_data_from_influx(self, measurement: str, start_date: str = "-3y") -> pd.DataFrame:
        query_api = db_manager.get_query_api()
        if not query_api:
            logger.error("API de consulta do InfluxDB indisponível.")
            return pd.DataFrame()
        logger.info(f"Lendo dados da measurement '{measurement}' desde {start_date}...")
        try:
            query = f'from(bucket:"{settings.influxdb_bucket}") |> range(start: {start_date}) |> filter(fn: (r) => r._measurement == "{measurement}") |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
            df = query_api.query_data_frame(query)
            if df.empty:
                logger.warning(f"Nenhum dado retornado para a measurement '{measurement}'.")
                return pd.DataFrame()
            df = df.rename(columns={"_time": "timestamp"})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            cols_to_drop = ['result', 'table']
            df = df.drop(columns=[col for col in cols_to_drop if col in df.columns])
            logger.info(f"✅ {len(df)} registos lidos do InfluxDB com sucesso.")
            return df
        except Exception as e:
            logger.error(f"❌ Erro ao ler dados do InfluxDB: {e}", exc_info=True)
            return pd.DataFrame()

    # <<< --- NOVO MÉTODO PARA BUSCAR FLUXO DE ORDENS --- >>>
    def _get_historical_agg_trades(self, symbol: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        """Busca dados de trades agregados (Order Flow) da Binance."""
        if not self.client:
            return pd.DataFrame()

        logger.info(f"Buscando dados de Fluxo de Ordens para {symbol} de {start_dt} até {end_dt}...")
        # A API da Binance pode ser instável para longos períodos, por isso buscamos em chunks de 1 dia
        all_trades = []
        current_start = start_dt
        while current_start < end_dt:
            current_end = current_start + pd.Timedelta(days=1)
            if current_end > end_dt:
                current_end = end_dt
            
            # Adicione estas variáveis antes do loop 'try'
            max_retries = 5
            retry_delay = 5  # segundos
            for attempt in range(max_retries):
                try:
                    trades = self.client.get_aggregate_trades(
                        symbol=symbol.replace('/', ''),
                        startTime=int(current_start.timestamp() * 1000),
                        endTime=int(current_end.timestamp() * 1000)
                    )
                    all_trades.extend(trades)
                    break  # Se a chamada for bem-sucedida, sai do loop de retentativas
                except (BinanceAPIException, BinanceRequestException) as e:
                    logger.warning(
                        f"Erro na API da Binance ao buscar agg_trades (tentativa {attempt + 1}/{max_retries}): {e}. "
                        f"Aguardando {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Aumenta o tempo de espera (exponential backoff)
                except Exception as e:
                     logger.error(f"Erro inesperado ao buscar agg_trades: {e}", exc_info=True)
                     break # Sai em caso de erro não relacionado à API
            
            current_start = current_end
            time.sleep(0.5) # Respeitar os limites da API

        if not all_trades:
            return pd.DataFrame()

        df_trades = pd.DataFrame(all_trades)
        # 'a': Trade ID, 'p': Price, 'q': Quantity, 'T': Timestamp, 'm': is maker
        df_trades = df_trades[['T', 'q', 'm']]
        df_trades['T'] = pd.to_datetime(df_trades['T'], unit='ms', utc=True)
        df_trades['q'] = pd.to_numeric(df_trades['q'])
        
        # Agrupa os trades por minuto
        df_agg = df_trades.groupby([pd.Grouper(key='T', freq='1min'), 'm'])['q'].sum().unstack(fill_value=0)
        df_agg = df_agg.rename(columns={True: 'maker_volume', False: 'taker_volume'})
        
        # O volume Taker é o volume agressivo. O volume Maker é o passivo.
        # Quando 'm' é False (não é maker), o comprador foi o agressor.
        # Por uma convenção um pouco confusa da Binance, 'm': True significa que o VENDEDOR foi o Taker (agressor).
        # Vamos simplificar: Taker Sell é quando o maker era comprador (m=True), Taker Buy quando o maker era vendedor (m=False).
        df_agg = df_agg.rename(columns={'maker_volume': 'taker_sell_volume', 'taker_volume': 'taker_buy_volume'})
        df_agg.index.name = 'timestamp'
        
        return df_agg[['taker_buy_volume', 'taker_sell_volume']]

    def _fetch_and_manage_btc_data(self, symbol: str, interval: str = '1m'):
        """
        Busca e gerencia os dados, combinando um longo histórico de velas (OHLCV)
        com dados recentes de fluxo de ordens.
        """
        measurement_name = f"btc_{symbol.lower().replace('/', '_')}_{interval}"
        end_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
        last_timestamp_in_db = self._query_last_timestamp(measurement_name)

        if not last_timestamp_in_db:
            # --- LÓGICA DE BOOTSTRAP (PRIMEIRA EXECUÇÃO) ---
            logger.info(f"Nenhum dado encontrado para '{measurement_name}'. Iniciando processo de bootstrap com histórico completo.")
            
            df_ohlcv_history = pd.DataFrame()

            # Prioridade 1: Ficheiro Histórico completo
            if os.path.exists(settings.data_paths.historical_data_file):
                logger.info(f"Carregando histórico completo de: '{settings.data_paths.historical_data_file}'")
                df_csv = pd.read_csv(settings.data_paths.historical_data_file, low_memory=False, on_bad_lines='skip')
                df_ohlcv_history = self._preprocess_kaggle_data(df_csv)
            elif os.path.exists(settings.data_paths.kaggle_bootstrap_file):
                 logger.info(f"Carregando histórico completo de: '{settings.data_paths.kaggle_bootstrap_file}'")
                 df_csv = pd.read_csv(settings.data_paths.kaggle_bootstrap_file, low_memory=False, on_bad_lines='skip')
                 df_ohlcv_history = self._preprocess_kaggle_data(df_csv)

            if not df_ohlcv_history.empty:
                logger.info(f"Histórico de {len(df_ohlcv_history)} velas carregado. Preparando para escrever no DB.")
                # Adiciona colunas de order flow vazias ao histórico antigo
                df_ohlcv_history['taker_buy_volume'] = 0.0
                df_ohlcv_history['taker_sell_volume'] = 0.0
                
                df_to_db = df_ohlcv_history[df_ohlcv_history.index >= '2018-01-01']
                self._write_dataframe_to_influx(df_to_db, measurement_name)
            else:
                logger.error("Nenhum ficheiro de histórico (historical_data.csv ou kaggle_bootstrap.csv) encontrado. Impossível fazer o bootstrap.")
                return # Aborta se não houver base histórica
            
            # Após o bootstrap, obtemos o último timestamp para a atualização incremental
            last_timestamp_in_db = self._query_last_timestamp(measurement_name)

        # --- LÓGICA DE ATUALIZAÇÃO INCREMENTAL ---
        if not last_timestamp_in_db:
            logger.error("Falha ao obter o timestamp após o bootstrap. Abortando.")
            return

        start_utc = last_timestamp_in_db + pd.Timedelta(minutes=1)
        if self.client and start_utc < end_utc:
            logger.info(f"Buscando novos dados de {start_utc.strftime('%Y-%m-%d %H:%M:%S')} até {end_utc.strftime('%Y-%m-%d %H:%M:%S')}...")
            
            # Busca novos dados de velas (OHLCV)
            df_ohlcv_new = self._get_historical_klines_binance(symbol, interval, start_utc, end_utc)
            
            # Busca novos dados de fluxo de ordens para o mesmo período
            df_orderflow_new = self._get_historical_agg_trades(symbol, start_utc, end_utc)
            
            if not df_ohlcv_new.empty:
                # Combina os dois novos dataframes, preenchendo com 0 se não houver dados de order flow
                df_combined = df_ohlcv_new.join(df_orderflow_new, how='left').fillna(0)
                self._write_dataframe_to_influx(df_combined, measurement_name)
        else:
            logger.info("Dados no DB já estão atualizados ou cliente offline.")
            
    # <<< O resto dos métodos (_get_historical_klines_binance, _preprocess_kaggle_data, run_data_pipeline) continuam iguais >>>
    def _get_historical_klines_binance(self, symbol: str, interval: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        logger.info(f"Baixando dados de {symbol} de {start_dt} até {end_dt}...")
        try:
            klines = self.client.get_historical_klines(symbol.replace('/', ''), interval, str(start_dt), str(end_dt))
            if not klines: return pd.DataFrame()
            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','qav','nt','tbbav','tbqav','ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df = df[['open','high','low','close','volume']].astype(float)
            return df
        except Exception as e:
            logger.error(f"Erro ao baixar dados da Binance: {e}", exc_info=True)
            return pd.DataFrame()

    def _preprocess_kaggle_data(self, df_kaggle: pd.DataFrame) -> pd.DataFrame:
        """
        Pré-processa dados de ficheiros CSV, lidando inteligentemente com
        diferentes formatos de timestamp (Unix ou String).
        """
        logger.debug("Pré-processando dados do ficheiro CSV...")
        
        column_mapping = {'Timestamp': 'timestamp', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
        df_kaggle = df_kaggle.rename(columns=lambda c: column_mapping.get(c, c))

        # --- LÓGICA INTELIGENTE DE PARSING DE DATA ---
        try:
            # Tenta converter como se fosse um número (Unix timestamp)
            df_kaggle['timestamp'] = pd.to_datetime(df_kaggle['timestamp'], unit='s', utc=True)
            logger.debug("Formato de timestamp Unix (numérico) detectado.")
        except (ValueError, TypeError):
            # Se falhar, tenta converter como se fosse texto (formato ISO)
            logger.debug("Formato Unix falhou, tentando formato de string de data/hora.")
            df_kaggle['timestamp'] = pd.to_datetime(df_kaggle['timestamp'], utc=True)
        # --- FIM DA LÓGICA INTELIGENTE ---

        df_kaggle.set_index('timestamp', inplace=True)
        
        final_columns = ['open', 'high', 'low', 'close', 'volume']
        df = df_kaggle[final_columns].copy()
        df.dropna(inplace=True)
        df = df.astype(float)
        logger.debug(f"Processamento do CSV concluído. {len(df)} registos válidos.")
        return df

    def run_data_pipeline(self, symbol: str = 'BTCUSDT', interval: str = '1m'):
        """
        Executa o pipeline completo de dados: atualiza o DB, lê os dados e enriquece com features.
        """
        measurement_name = f"btc_{symbol.lower().replace('/', '_')}_{interval}"
        logger.info("🚀 INICIANDO PIPELINE DE DADOS E FEATURES 🚀")
        
        # Passo 1: Garantir que o DB está populado e atualizado.
        self._fetch_and_manage_btc_data(symbol, interval)
        
        # Passo 2: Ler os dados do DB para um DataFrame.
        full_dataframe = self.read_data_from_influx(measurement_name, start_date="-3y")
        
        if full_dataframe.empty:
            logger.error("Nenhum dado pôde ser lido do InfluxDB. Pipeline abortado.")
            return None

        # Passo 3: Enriquecer o DataFrame com todas as features
        # Importamos a função aqui para evitar importações circulares
        from src.core.feature_engineering import add_all_features
        df_with_features = add_all_features(full_dataframe)
        
        logger.info("Amostra dos dados finais com features (incluindo CVD):")
        # Mostra as colunas mais importantes, incluindo as novas de order flow
        print(df_with_features[['close', 'volume', 'taker_buy_volume', 'taker_sell_volume', 'cvd', 'cvd_short_term']].tail())
        
        logger.info("✅ PIPELINE DE DADOS E FEATURES CONCLUÍDO ✅")
        return df_with_features


if __name__ == '__main__':
    settings.influxdb_bucket = "btc_data"
    # Adicionamos o path aqui para garantir que o script de teste funcione
    # sem precisar do bloco de resolução de path em todos os ficheiros
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    data_manager = DataManager()
    data_manager.run_data_pipeline(symbol='BTCUSDT')