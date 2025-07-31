# Ficheiro: scripts/data_pipeline.py (VERSÃO CORRIGIDA)

import os
import sys
import datetime
import pandas as pd
import time
import requests
import yfinance as yf
import gc
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from tqdm import tqdm
from typing import Optional
from dateutil.relativedelta import relativedelta

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config_manager import settings
from src.database_manager import db_manager
from src.logger import logger
from src.core.feature_engineering import add_all_features
from src.core.situational_awareness import SituationalAwareness

class DataPipeline:
    def __init__(self):
        self.binance_client = self._init_binance_client()

    def _init_binance_client(self) -> Optional[Client]:
        if settings.app.force_offline_mode: return None
        try:
            # --- INÍCIO DA CORREÇÃO 1: CAMINHO CORRETO PARA AS API KEYS ---
            api_key = settings.api_keys.binance_testnet_api_key if settings.app.use_testnet else settings.api_keys.binance_api_key
            api_secret = settings.api_keys.binance_testnet_api_secret if settings.app.use_testnet else settings.api_keys.binance_api_secret
            # --- FIM DA CORREÇÃO 1 ---
            
            if not api_key or not api_secret:
                logger.warning("API Key/Secret da Binance não encontradas.")
                return None
            client = Client(api_key, api_secret, tld='com', testnet=settings.app.use_testnet)
            client.ping()
            logger.info(f"✅ Cliente Binance inicializado em modo {'TESTNET' if settings.app.use_testnet else 'REAL'}.")
            return client
        except Exception as e:
            logger.warning(f"❌ FALHA NA CONEXÃO com a Binance: {e}.")
            return None

    # ... (outros métodos como _write_dataframe_to_influx, _query_last_timestamp, etc. permanecem os mesmos)

    def run_sentiment_pipeline(self):
        """Busca o Índice de Medo e Ganância e o salva no InfluxDB."""
        logger.info("--- ❤️ INICIANDO PIPELINE DE SENTIMENTO (FONTE: ALTERNATIVE.ME) ❤️ ---")
        measurement_name = "sentiment_fear_and_greed"
        
        try:
            last_ts_in_db = self._query_last_timestamp(measurement_name)
            url = "https://api.alternative.me/fng/?limit=730&format=json"
            response = requests.get(url)
            response.raise_for_status()
            
            data = response.json().get('data')
            if not data:
                logger.warning("API de Sentimento não retornou dados.")
                return

            # --- INÍCIO DA CORREÇÃO 2: LÓGICA DE CRIAÇÃO DO DATAFRAME ---
            # Passo 1: Criar o DataFrame base a partir dos dados JSON
            df = pd.DataFrame(data)

            # Passo 2: Processar e formatar o DataFrame
            df_processed = df.rename(columns={'value': 'fear_and_greed'})
            df_processed['timestamp'] = pd.to_datetime(pd.to_numeric(df_processed['timestamp']), unit='s', utc=True)
            df_processed = df_processed.set_index('timestamp')[['fear_and_greed']]
            # --- INÍCIO DA CORREÇÃO DO TIPO DE DADO ---
            # Garante que o tipo de dado é int para evitar conflito com o InfluxDB
            df_processed['fear_and_greed'] = pd.to_numeric(df_processed['fear_and_greed']).astype(int)
            # --- FIM DA CORREÇÃO DO TIPO DE DADO ---
            
            if last_ts_in_db:
                df_processed = df_processed[df_processed.index > last_ts_in_db]

            if df_processed.empty:
                logger.info("✅ Dados de Sentimento já estão atualizados.")
                return

            self._write_dataframe_to_influx(df_processed.resample('1min').ffill(), measurement_name)
        except Exception as e:
            logger.error(f"❌ Falha no pipeline de Sentimento: {e}", exc_info=True)


    def _write_dataframe_to_influx(self, df: pd.DataFrame, measurement: str, batch_size: int = 1000):
        write_api = db_manager.get_write_api()
        if not write_api:
            logger.error(f"API de escrita do InfluxDB indisponível. Escrita para '{measurement}' abortada.")
            return
        df_to_write = df.reset_index()
        if 'timestamp' not in df_to_write.columns:
            logger.error(f"Erro Crítico: A coluna 'timestamp' não foi encontrada no DataFrame ao tentar escrever para '{measurement}'.")
            return
            
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
                    bucket=settings.database.bucket,
                    record=batch,
                    data_frame_measurement_name=measurement,
                    data_frame_timestamp_column="timestamp"
                )
                del batch
                gc.collect()
                time.sleep(0.1)

            logger.info(f"✅ Escrita para '{measurement}' concluída com sucesso.")
        except Exception as e:
            logger.error(f"❌ Erro ao escrever dados para o InfluxDB: {e}", exc_info=True)

    def _query_last_timestamp(self, measurement: str) -> Optional[pd.Timestamp]:
        query_api = db_manager.get_query_api()
        if not query_api: return None
        query = f'from(bucket:"{settings.database.bucket}") |> range(start: 0) |> filter(fn: (r) => r._measurement == "{measurement}") |> last() |> keep(columns: ["_time"])'
        try:
            result = query_api.query(query)
            if not result or not result[0].records: return None
            return pd.to_datetime(result[0].records[0].get_time()).tz_convert('UTC')
        except Exception as e:
            logger.error(f"Erro ao buscar o último timestamp do InfluxDB: {e}")
            return None

    def _find_gaps_in_db(self, measurement: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """
        Encontra lacunas de dados em uma medição do InfluxDB, verificando dia a dia.
        Retorna uma lista de tuplas, onde cada tupla representa o início e o fim de uma lacuna.
        """
        logger.info(f"Iniciando verificação de lacunas no banco de dados para '{measurement}' de {start_date.date()} a {end_date.date()}.")
        query_api = db_manager.get_query_api()
        if not query_api:
            logger.error("API de consulta do InfluxDB indisponível. Não é possível encontrar lacunas.")
            return []

        all_missing_timestamps = []
        
        # Itera dia a dia para evitar sobrecarga de memória
        for day in tqdm(pd.date_range(start=start_date, end=end_date, freq='D'), desc="Verificando Lacunas no DB"):
            day_start = day.isoformat()
            day_end = (day + pd.Timedelta(days=1)).isoformat()
            
            query = f'''
            import "date"
            
            timestamps = from(bucket: "{settings.database.bucket}")
                |> range(start: {day_start}, stop: {day_end})
                |> filter(fn: (r) => r._measurement == "{measurement}")
                |> aggregateWindow(every: 1m, fn: count)
                |> filter(fn: (r) => r._value == 0)
                |> keep(columns: ["_time"])

            timestamps
            '''
            try:
                result = query_api.query(query)
                for table in result:
                    for record in table.records:
                        all_missing_timestamps.append(record.get_time())
            except Exception as e:
                logger.error(f"Erro ao consultar lacunas para o dia {day.date()}: {e}")
        
        if not all_missing_timestamps:
            logger.info("Nenhuma lacuna encontrada no banco de dados.")
            return []

        logger.warning(f"Encontrados {len(all_missing_timestamps)} minutos faltantes. Consolidando em blocos...")
        
        all_missing_timestamps.sort()
        
        # Consolida os timestamps faltantes em blocos contíguos
        missing_blocks = []
        if all_missing_timestamps:
            start_block = all_missing_timestamps[0]
            for i in range(1, len(all_missing_timestamps)):
                if (all_missing_timestamps[i] - all_missing_timestamps[i-1]) > pd.Timedelta(minutes=1):
                    missing_blocks.append((start_block, all_missing_timestamps[i-1]))
                    start_block = all_missing_timestamps[i]
            missing_blocks.append((start_block, all_missing_timestamps[-1]))
            
        logger.info(f"Consolidado em {len(missing_blocks)} blocos de dados faltantes.")
        return missing_blocks

    # Ficheiro: scripts/data_pipeline.py

    def read_data_in_range(self, measurement: str, start_date: str, end_date: str) -> pd.DataFrame:
        query_api = db_manager.get_query_api()
        if not query_api:
            logger.error(f"API de consulta do InfluxDB indisponível ao ler range para '{measurement}'.")
            return pd.DataFrame()
        logger.debug(f"Lendo dados de '{measurement}' de {start_date} a {end_date}")
        try:
            query = f'''
            from(bucket:"{settings.database.bucket}")
                |> range(start: {start_date}, stop: {end_date})
                |> filter(fn: (r) => r._measurement == "{measurement}")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            df = query_api.query_data_frame(query)
            if df.empty:
                return pd.DataFrame()

            df = df.rename(columns={"_time": "timestamp"})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')

            # --- INÍCIO DA CORREÇÃO DEFINITIVA ---
            # Corrigido o erro de digitação de 'stop' para '_stop'
            cols_to_drop = ['result', 'table', '_start', '_stop', '_measurement']
            df_cleaned = df.drop(columns=[col for col in cols_to_drop if col in df.columns], errors='ignore')
            # --- FIM DA CORREÇÃO DEFINITIVA ---

            # Garante que as colunas essenciais para os indicadores técnicos sejam numéricas.
            ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in ohlcv_cols:
                if col in df_cleaned.columns:
                    df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors='coerce')

            return df_cleaned

        except Exception as e:
            logger.error(f"❌ Erro ao ler range do InfluxDB: {e}", exc_info=True)
            return pd.DataFrame()

    def _get_historical_klines_binance(self, symbol: str, interval: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        logger.info(f"Baixando dados de velas (OHLCV) para {symbol} de {start_dt} até {end_dt}...")
        try:
            klines = self.binance_client.get_historical_klines(symbol.replace('/', ''), interval, str(start_dt), str(end_dt))
            if not klines: return pd.DataFrame()
            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','qav','nt','tbbav','tbqav','ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df = df[['open','high','low','close','volume']].astype(float)
            if df.index.tz is None:
                df = df.tz_localize('UTC')
            else:
                df = df.tz_convert('UTC')
            return df
        except Exception as e:
            logger.error(f"Erro ao baixar dados da Binance: {e}", exc_info=True)
            return pd.DataFrame()

    def _get_historical_agg_trades(self, symbol: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        if not self.binance_client: return pd.DataFrame()
        logger.info(f"Buscando dados de Fluxo de Ordens para {symbol} de {start_dt} até {end_dt}...")
        all_trades = []
        current_start = start_dt
        pbar = tqdm(total=(end_dt - start_dt).days + 1, desc="Buscando Order Flow")
        while current_start < end_dt:
            current_end = current_start + pd.Timedelta(days=1)
            if current_end > end_dt: current_end = end_dt
            max_retries = 5
            retry_delay = 5
            for attempt in range(max_retries):
                try:
                    trades = self.binance_client.get_aggregate_trades(symbol=symbol.replace('/', ''), startTime=int(current_start.timestamp() * 1000), endTime=int(current_end.timestamp() * 1000))
                    all_trades.extend(trades)
                    break
                except (BinanceAPIException, BinanceRequestException) as e:
                    logger.warning(f"Erro na API da Binance (tentativa {attempt + 1}/{max_retries}): {e}. Aguardando {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                except Exception as e:
                     logger.error(f"Erro inesperado ao buscar agg_trades: {e}", exc_info=True)
                     break
            pbar.update(1)
            current_start = current_end
            time.sleep(0.5)
        pbar.close()
        if not all_trades: return pd.DataFrame()
        df_trades = pd.DataFrame(all_trades)
        df_trades = df_trades[['T', 'q', 'm']]
        df_trades['T'] = pd.to_datetime(df_trades['T'], unit='ms', utc=True)
        df_trades['q'] = pd.to_numeric(df_trades['q'])
        df_agg = df_trades.groupby([pd.Grouper(key='T', freq='1min'), 'm'])['q'].sum().unstack(fill_value=0)
        df_agg = df_agg.rename(columns={True: 'taker_sell_volume', False: 'taker_buy_volume'})
        if 'taker_buy_volume' not in df_agg.columns: df_agg['taker_buy_volume'] = 0.0
        if 'taker_sell_volume' not in df_agg.columns: df_agg['taker_sell_volume'] = 0.0
        df_agg.index.name = 'timestamp'
        return df_agg[['taker_buy_volume', 'taker_sell_volume']]

    def _preprocess_kaggle_data(self, df_kaggle: pd.DataFrame) -> pd.DataFrame:
        logger.debug("Pré-processando dados do ficheiro CSV...")
        
        df_kaggle.columns = [col.lower() for col in df_kaggle.columns]
        column_mapping = {'timestamp': 'timestamp', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume', 'date': 'timestamp'}
        df_kaggle = df_kaggle.rename(columns=column_mapping)
        
        try:
            df_kaggle['timestamp'] = pd.to_datetime(df_kaggle['timestamp'], unit='s', utc=True)
        except (ValueError, TypeError):
            df_kaggle['timestamp'] = pd.to_datetime(df_kaggle['timestamp'], utc=True)
            
        df_kaggle.set_index('timestamp', inplace=True)
        final_columns = ['open', 'high', 'low', 'close', 'volume']
        df = df_kaggle[final_columns].copy()
        df.dropna(inplace=True)
        df = df.astype(float)
        return df

    def run_order_flow_backfill(self, symbol: str, measurement_name: str, months_to_backfill: int = 12):
        """
        Executa um backfill robusto de dados de fluxo de ordens (agg_trades)
        para um período histórico, processando mês a mês para trás.
        """
        if not self.binance_client:
            logger.warning("Cliente Binance offline. Backfill de fluxo de ordens abortado.")
            return

        logger.info(f"--- 🌊 INICIANDO BACKFILL ROBUSTO DE FLUXO DE ORDENS ({months_to_backfill} meses) 🌊 ---")
        end_date = self._query_last_timestamp(measurement_name) or datetime.datetime.now(datetime.timezone.utc)
        start_date = end_date - relativedelta(months=months_to_backfill)

        current_start = start_date
        pbar = tqdm(total=months_to_backfill, desc="Backfill Order Flow")
        while current_start < end_date:
            current_end = current_start + relativedelta(months=1)
            if current_end > end_date:
                current_end = end_date
            
            logger.info(f"Buscando dados de fluxo de ordens de {current_start.date()} a {current_end.date()}")
            df_orderflow = self._get_historical_agg_trades(symbol, current_start, current_end)
            
            if not df_orderflow.empty:
                self._write_dataframe_to_influx(df_orderflow, measurement_name)
            else:
                logger.warning(f"Nenhum dado de fluxo de ordens encontrado para {current_start.strftime('%Y-%m')}.")
            
            current_start = current_end
            pbar.update(1)
        pbar.close()
        logger.info("--- ✅ BACKFILL DE FLUXO DE ORDENS CONCLUÍDO ---")

    def run_btc_pipeline(self, symbol: str, interval: str = '1m'):
        """
        Pipeline principal para dados de BTC, com lógica de atualização, preenchimento de lacunas e persistência em CSV.
        """
        measurement_name = f"btc_{symbol.lower().replace('/', '_')}_{interval}"
        csv_path = settings.data_paths.historical_data_file
        
        # Lista para armazenar todos os dataframes (histórico, lacunas, novos)
        all_dfs = []

        # Carrega dados históricos do CSV, se existir
        if os.path.exists(csv_path):
            logger.info(f"Lendo histórico de BTC de {csv_path}...")
            historical_data = pd.read_csv(csv_path, index_col='timestamp', parse_dates=True)
            if not historical_data.empty:
                if historical_data.index.tz is None:
                    historical_data.index = historical_data.index.tz_localize('UTC')
                else:
                    historical_data.index = historical_data.index.tz_convert('UTC')
                all_dfs.append(historical_data)
        else:
            historical_data = pd.DataFrame()

        # Identifica e preenche lacunas nos dados históricos
        if not historical_data.empty and self.binance_client:
            full_range = pd.date_range(start=historical_data.index.min(), end=historical_data.index.max(), freq='1min', tz='UTC')
            missing_timestamps = full_range.difference(historical_data.index)
            
            if not missing_timestamps.empty:
                logger.warning(f"Encontradas {len(missing_timestamps)} lacunas nos dados históricos. Preenchendo...")
                missing_blocks = []
                if len(missing_timestamps) > 0:
                    start_block = missing_timestamps[0]
                    for i in range(1, len(missing_timestamps)):
                        if missing_timestamps[i] - missing_timestamps[i-1] > pd.Timedelta(minutes=1):
                            missing_blocks.append((start_block, missing_timestamps[i-1]))
                            start_block = missing_timestamps[i]
                    missing_blocks.append((start_block, missing_timestamps[-1]))

                for start_gap, end_gap in missing_blocks:
                    logger.info(f"Preenchendo lacuna de {start_gap} a {end_gap}")
                    gap_data = self._get_historical_klines_binance(symbol, interval, start_gap, end_gap)
                    if not gap_data.empty:
                        all_dfs.append(gap_data)

        # Determina a data de início para buscar novos dados
        # Usa o dataframe combinado até agora para encontrar o último timestamp
        temp_combined_df = pd.concat(all_dfs) if all_dfs else pd.DataFrame()
        start_utc = (temp_combined_df.index.max() + pd.Timedelta(minutes=1)) if not temp_combined_df.empty else pd.to_datetime(settings.data_pipeline.start_date_ingestion, utc=True)
        end_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)

        # Busca novos dados se necessário
        df_new = pd.DataFrame()
        if self.binance_client and start_utc < end_utc:
            logger.info(f"Buscando novos dados de BTC de {start_utc.strftime('%Y-%m-%d %H:%M:%S')} até {end_utc.strftime('%Y-%m-%d %H:%M:%S')}...")
            df_new = self._get_historical_klines_binance(symbol, interval, start_utc, end_utc)
            if not df_new.empty:
                all_dfs.append(df_new)
            else:
                logger.info("Nenhum dado novo de BTC encontrado na Binance.")
        else:
            logger.info("Dados de BTC no CSV e DB já estão atualizados ou cliente offline.")

        # Combina todos os dataframes (histórico, lacunas, novos) e salva o CSV
        if all_dfs:
            df_combined = pd.concat(all_dfs)
            df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
            df_combined.sort_index(inplace=True)
            df_combined.to_csv(csv_path)
            logger.info(f"✅ CSV de histórico do BTC atualizado com {len(df_combined)} registros em {csv_path}")
        else:
            df_combined = pd.DataFrame() # Garante que df_combined exista

        # Lógica de escrita no InfluxDB consolidada
        if not df_combined.empty:
            last_timestamp_in_db = self._query_last_timestamp(measurement_name)
            
            if last_timestamp_in_db is None:
                # Bootstrap: DB está vazio, escreve tudo
                logger.info(f"Nenhum dado encontrado em '{measurement_name}'. Fazendo bootstrap com {len(df_combined)} registros...")
                self._write_dataframe_to_influx(df_combined, measurement_name)
                self.run_order_flow_backfill(symbol, measurement_name, months_to_backfill=24)
            else:
                # Incremental: Escreve apenas dados mais recentes que os existentes no DB
                data_to_write = df_combined[df_combined.index > last_timestamp_in_db]
                if not data_to_write.empty:
                    logger.info(f"Escrevendo {len(data_to_write)} novos pontos de dados no InfluxDB...")
                    self._write_dataframe_to_influx(data_to_write, measurement_name)
                else:
                    logger.info("Nenhum dado novo para escrever no InfluxDB.")
            

    def run_macro_pipeline(self):
        """
        Busca e atualiza dados macroeconômicos do Yahoo Finance, usando CSVs como
        cache local resiliente antes de escrever no banco de dados.
        Esta versão combina a robustez da reescrita total do cache com a eficiência
        da escrita incremental no banco de dados.
        """
        logger.info("--- 🌐 INICIANDO PIPELINE DE DADOS MACRO (LÓGICA HÍBRIDA ROBUSTA) 🌐 ---")
        macro_dir = settings.data_paths.macro_data_dir
        macro_assets = {
            "dxy": {"ticker": "DX-Y.NYB", "path": os.path.join(macro_dir, "DXY.csv")},
            "vix": {"ticker": "^VIX", "path": os.path.join(macro_dir, "VIX.csv")},
            "gold": {"ticker": "GC=F", "path": os.path.join(macro_dir, "GOLD.csv")},
            "tnx": {"ticker": "^TNX", "path": os.path.join(macro_dir, "TNX.csv")},
            "spx": {"ticker": "^GSPC", "path": os.path.join(macro_dir, "SPX.csv")},
            "ndx": {"ticker": "^IXIC", "path": os.path.join(macro_dir, "NDX.csv")},
            "uso": {"ticker": "USO", "path": os.path.join(macro_dir, "USO.csv")}
        }

        os.makedirs(macro_dir, exist_ok=True)
        all_macro_data_for_db = []

        for name, asset_info in macro_assets.items():
            logger.info(f"--- Processando ativo macro: {name.upper()} ---")
            historical_data = pd.DataFrame()
            file_path = asset_info["path"]
            
            # Tenta ler o cache local. Se falhar ou o ficheiro estiver vazio, não há problema.
            if os.path.exists(file_path):
                try:
                    historical_data = pd.read_csv(file_path, index_col='Date', parse_dates=True)
                    if not historical_data.empty:
                        logger.info(f"Cache local para {name.upper()} lido com sucesso. Último registo: {historical_data.index.max().date()}")
                except (pd.errors.EmptyDataError, IndexError):
                    logger.warning(f"Cache local para {name.upper()} em {file_path} está vazio ou corrompido. Será recriado.")
                    historical_data = pd.DataFrame() # Garante que o dataframe está vazio
            
            # Determina a data de início para o download
            start_date_for_download = (historical_data.index.max() + pd.Timedelta(days=1)) if not historical_data.empty else pd.to_datetime('2018-01-01')
            end_date_for_download = pd.to_datetime(datetime.date.today() + datetime.timedelta(days=1))

            new_data = pd.DataFrame()
            if start_date_for_download < end_date_for_download:
                logger.info(f"Buscando dados para {name.upper()} de {start_date_for_download.date()} a {(end_date_for_download - pd.Timedelta(days=1)).date()}.")
                try:
                    new_data = yf.download(asset_info["ticker"], 
                                        start=start_date_for_download, 
                                        end=end_date_for_download, 
                                        progress=False,
                                        auto_adjust=False)
                    if new_data.empty:
                        logger.warning(f"Nenhum dado novo retornado pelo yfinance para {name.upper()}.")
                    else:
                        logger.info(f"✅ {len(new_data)} novos registos baixados para {name.upper()}.")
                except Exception as e:
                    logger.error(f"❌ Falha no download de dados para {name.upper()}: {e}")
            else:
                logger.info(f"Dados para {name.upper()} no cache local já estão atualizados.")

            # Combina, limpa e salva o cache
            combined_data = pd.concat([historical_data, new_data])
            if not combined_data.empty:
                combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                combined_data.sort_index(inplace=True)
                
                # Limpeza das colunas
                combined_data.columns = [(col[0] if isinstance(col, tuple) else col).lower() for col in combined_data.columns]
                if 'adj close' in combined_data.columns:
                    combined_data.drop(columns=['adj close'], inplace=True)
                if 'volume' not in combined_data.columns: 
                    combined_data['volume'] = 0

                final_cols = ['open', 'high', 'low', 'close', 'volume']
                data_to_save = combined_data[final_cols]
                data_to_save.index.name = 'Date'
                data_to_save.to_csv(file_path)
                logger.debug(f"Cache CSV para {name.upper()} salvo/atualizado em {file_path}.")
                
                # Prepara os dados para a tabela do DB
                data_for_db = data_to_save.copy()
                if data_for_db.index.tz is None:
                    data_for_db.index = data_for_db.index.tz_localize('UTC')
                data_for_db.columns = [f"{name}_{col.lower()}" for col in data_for_db.columns]
                all_macro_data_for_db.append(data_for_db)
            else:
                logger.warning(f"Nenhum dado (nem histórico, nem novo) disponível para {name.upper()}.")

        # Lógica otimizada para escrita no banco de dados
        if all_macro_data_for_db:
            logger.info("Combinando todos os dados macro para escrita no banco de dados...")
            df_macro_combined = pd.concat(all_macro_data_for_db, axis=1)
            df_macro_combined.ffill(inplace=True)
            df_macro_combined.dropna(how='all', inplace=True)

            measurement_name = "macro_data_1m"
            last_ts_in_db = self._query_last_timestamp(measurement_name)

            df_to_process = df_macro_combined
            if last_ts_in_db:
                df_to_process = df_macro_combined[df_macro_combined.index > last_ts_in_db]

            if df_to_process.empty:
                logger.info("✅ Dados macro já estão sincronizados com o banco de dados.")
                return

            logger.info(f"Reamostrando {len(df_to_process)} registos diários para 1 minuto...")
            df_to_write = df_to_process.resample('1min').ffill()
            df_to_write.index.name = 'timestamp'
            self._write_dataframe_to_influx(df_to_write, measurement_name)
        else:
            logger.error("Nenhum dado macro foi processado. O banco de dados não será atualizado.")



    def validate_data(self, df: pd.DataFrame) -> bool:
        """
        Executa uma série de verificações de sanidade nos dados finais.
        """
        logger.info("--- 🔬 EXECUTANDO VALIDAÇÃO DE DADOS (SANITY CHECKS) 🔬 ---")
        is_valid = True
        
        if df.isnull().values.any():
            logger.error("Validação Falhou: Foram encontrados valores NULOS nos dados finais.")
            is_valid = False
            
        time_diffs = df.index.to_series().diff()
        max_gap = time_diffs.max()
        if max_gap > pd.Timedelta(minutes=60):
             logger.warning(f"Alerta de Validação: Encontrado grande gap nos dados de {max_gap}.")
             
        essential_cols = ['dxy_close', 'spx_close']
        if not all(col in df.columns for col in essential_cols):
            logger.warning("Alerta de Validação: Colunas macro essenciais (DXY, SPX) estão em falta.")

        if is_valid:
            logger.info("--- ✅ VALIDAÇÃO DE DADOS CONCLUÍDA COM SUCESSO ---")
        else:
            logger.error("--- ❌ VALIDAÇÃO DE DADOS FALHOU. VERIFIQUE OS LOGS. ---")
            
        return is_valid

        
    def _train_and_save_regime_model(self):
        """
        Lógica de treino para o modelo de SituationalAwareness.
        Esta função é chamada automaticamente pelo pipeline se o modelo não existir.
        """
        logger.info("--- 🧠 Modelo de Regimes não encontrado. INICIANDO TREINAMENTO... 🧠 ---")
        
        # Carrega um período de dados brutos robusto para o treino
        start_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=730)).isoformat()
        end_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        df_btc = self.read_data_in_range("btc_btcusdt_1m", start_date, end_date)
        df_macro = self.read_data_in_range("macro_data_1m", start_date, end_date)
        
        if df_btc.empty:
            logger.error("Nenhum dado de BTC encontrado para treinar o modelo de regimes. Abortando.")
            return False # Retorna falha

        df_combined = df_btc.join(df_macro, how='left').ffill()
        df_with_features = add_all_features(df_combined)
        
        sa_model = SituationalAwareness(n_regimes=4)
        sa_model.fit(df_with_features)
        
        model_path = os.path.join(settings.data_paths.models_dir, 'situational_awareness.joblib')
        sa_model.save_model(model_path)
        return True # Retorna sucesso

    def _get_derivatives_data(self, symbol: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
            """Busca dados de Derivativos (Funding Rate, Open Interest) da Binance."""
            if not self.binance_client: return pd.DataFrame()
            logger.info(f"Buscando dados de Derivativos para {symbol} de {start_dt} a {end_dt}...")
            
            try:
                # --- INÍCIO DA CORREÇÃO DO ERRO DE ATRIBUTO ---
                # As funções para futuros usam o prefixo 'fapi_'
                funding_rates = self.binance_client.fapi_get_funding_rate(symbol=symbol.replace('/', ''), startTime=int(start_dt.timestamp() * 1000), limit=1000)
                oi_stats = self.binance_client.fapi_get_open_interest_hist(symbol=symbol.replace('/', ''), period='1h', limit=500, startTime=int(start_dt.timestamp() * 1000))
                # --- FIM DA CORREÇÃO ---

                df_funding = pd.DataFrame(funding_rates)
                if not df_funding.empty:
                    df_funding['fundingTime'] = pd.to_datetime(df_funding['fundingTime'], unit='ms', utc=True)
                    df_funding = df_funding.rename(columns={'fundingTime': 'timestamp', 'fundingRate': 'funding_rate'}).set_index('timestamp')[['funding_rate']]
                    df_funding['funding_rate'] = pd.to_numeric(df_funding['funding_rate'])

                df_oi = pd.DataFrame(oi_stats)
                if not df_oi.empty:
                    df_oi['timestamp'] = pd.to_datetime(df_oi['timestamp'], unit='ms', utc=True)
                    df_oi = df_oi.rename(columns={'sumOpenInterestValue': 'open_interest'}).set_index('timestamp')[['open_interest']]
                    df_oi['open_interest'] = pd.to_numeric(df_oi['open_interest'])

                if df_funding.empty and df_oi.empty:
                    return pd.DataFrame()
                
                return df_funding.join(df_oi, how='outer')

            # --- INÍCIO DA CORREÇÃO DO ERRO DE ATRIBUTO ---
            except AttributeError:
                logger.error("Falha ao buscar dados de derivativos: 'Client' object has no attribute 'fapi_get...'.")
                logger.warning("Este erro geralmente ocorre devido a uma versão desatualizada da biblioteca 'python-binance'.")
                logger.warning("O pipeline continuará sem dados de derivativos para este lote.")
                return pd.DataFrame()
            # --- FIM DA CORREÇÃO DO ERRO DE ATRIBUTO ---
            except Exception as e:
                logger.error(f"Erro ao buscar dados de derivativos: {e}", exc_info=True)
                return pd.DataFrame()

    # Ficheiro: scripts/data_pipeline.py (SUBSTITUA ESTA FUNÇÃO)

    def run_full_pipeline(self):
        """
        Executa o pipeline completo, agora com uma etapa de limpeza de dados inteligente
        para garantir que todos os lotes passem na validação.
        """
        # --- FASE 0: INGESTÃO DE DADOS BRUTOS (sem alterações) ---
        self.run_btc_pipeline(symbol='BTCUSDT', interval='1m')
        self.run_macro_pipeline()

        # --- FASE 1: PREPARAÇÃO (Treino automático do modelo de regimes) ---
        sa_model_path = os.path.join(settings.data_paths.models_dir, 'situational_awareness.joblib')
        if not os.path.exists(sa_model_path):
            if not self._train_and_save_regime_model():
                logger.critical("Falha ao treinar o modelo de regimes. Pipeline abortado.")
                return

        self.run_sentiment_pipeline()

        # --- FASE 2: PROCESSAMENTO, ENRIQUECIMENTO E LIMPEZA EM LOTES ---
        logger.info("--- 🔄 INICIANDO PROCESSAMENTO DA TABELA MESTRE EM LOTES MENSAIS 🔄 ---")

        situational_awareness_model = SituationalAwareness.load_model(sa_model_path)
        if not situational_awareness_model:
            logger.critical("Modelo de SituationalAwareness não pôde ser carregado. Abortando.")
            return

        start_date = pd.to_datetime('2018-01-01', utc=True)
        end_date = pd.to_datetime(datetime.date.today() + datetime.timedelta(days=1), utc=True)
        
        current_date = start_date
        total_months = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month
        pbar = tqdm(total=total_months, desc="Processando Tabela Mestre")

        # --- INÍCIO DA CORREÇÃO CRÍTICA ---
        # O período de warmup precisa ser maior que o maior lookback das features (ex: correlação de 30 dias).
        # Aumentamos para 35 dias para ter uma margem de segurança.
        warmup_period = pd.Timedelta(days=35)
        # --- FIM DA CORREÇÃO CRÍTICA ---

        while current_date < end_date:
            # Define o período de processamento real e o período de busca de dados (com warmup)
            processing_start_date = current_date
            fetch_start_date = processing_start_date - warmup_period
            chunk_end_date = (current_date + relativedelta(months=1))

            chunk_start = fetch_start_date.isoformat()
            chunk_end = chunk_end_date.isoformat()
            
            logger.debug(f"Processando lote de {processing_start_date.strftime('%Y-%m')}...")
            logger.info(f"Período de fetch (com warmup): {chunk_start} a {chunk_end}")

            # 1. Leitura e Combinação dos Dados Brutos
            df_btc_chunk = self.read_data_in_range("btc_btcusdt_1m", chunk_start, chunk_end)
            if df_btc_chunk.empty:
                logger.warning(f"Nenhum dado de BTC para o período {current_date.strftime('%Y-%m')}. A saltar.")
                current_date += relativedelta(months=1)
                pbar.update(1)
                continue
            
            df_macro_chunk = self.read_data_in_range("macro_data_1m", chunk_start, chunk_end)
            df_sentiment_chunk = self.read_data_in_range("sentiment_fear_and_greed", chunk_start, chunk_end)
            
            df_combined = df_btc_chunk.join(df_macro_chunk, how='left').join(df_sentiment_chunk, how='left')

            # 2. LIMPEZA INTELIGENTE
            df_combined.ffill(inplace=True)
            df_with_features = add_all_features(df_combined)
            
            # Remove os dados de warmup, mantendo apenas os dados do mês corrente para processamento.
            df_with_features = df_with_features[df_with_features.index >= processing_start_date]

            expected_features = settings.data_pipeline.regime_features
            if not all(feature in df_with_features.columns for feature in expected_features):
                logger.error(f"FATAL: Features esperadas {expected_features} não foram criadas pela engenharia de features. A saltar lote.")
                current_date += relativedelta(months=1)
                pbar.update(1)
                continue

            df_with_regimes = situational_awareness_model.transform(df_with_features)

            initial_rows = len(df_with_regimes)
            df_final = df_with_regimes.dropna()
            final_rows = len(df_final)

            if initial_rows > final_rows:
                logger.info(f"Limpeza de NaNs: {initial_rows - final_rows} linhas incalculáveis removidas do lote {current_date.strftime('%Y-%m')}.")
            
            # 6. VALIDAÇÃO E SALVAMENTO
            if not df_final.empty and self.validate_data(df_final):
                self._write_dataframe_to_influx(df_final, "features_master_table")
            else:
                if df_final.empty:
                    logger.warning(f"Lote {current_date.strftime('%Y-%m')} ficou vazio após a limpeza. Nada para salvar.")
                else:
                    logger.error(f"Validação falhou para o lote {current_date.strftime('%Y-%m')}. Este lote não será salvo.")
            
            del df_btc_chunk, df_macro_chunk, df_sentiment_chunk, df_combined, df_with_features, df_with_regimes, df_final
            gc.collect()

            current_date += relativedelta(months=1)
            pbar.update(1)
        
        pbar.close()
        logger.info("🎉🎉🎉 PIPELINE INDUSTRIAL CONCLUÍDO! A FONTE DA VERDADE ESTÁ PRONTA. 🎉🎉🎉")


if __name__ == '__main__':
    pipeline = DataPipeline()
    pipeline.run_full_pipeline()