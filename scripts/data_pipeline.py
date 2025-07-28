# Ficheiro: scripts/data_pipeline.py (VERSÃO INDUSTRIAL DEFINITIVA)

import os
import sys
import datetime
import pandas as pd
import time
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

class DataPipeline:
    """
    O motor ETL (Extract, Transform, Load) do projeto.
    """
    def __init__(self):
        self.binance_client = self._init_binance_client()

    def _init_binance_client(self) -> Optional[Client]:
        if settings.app.force_offline_mode: return None
        try:
            api_key = settings.binance_testnet_api_key if settings.app.use_testnet else settings.binance_api_key
            api_secret = settings.binance_testnet_api_secret if settings.app.use_testnet else settings.binance_api_secret
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

    def _write_dataframe_to_influx(self, df: pd.DataFrame, measurement: str, batch_size: int = 2000):
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
                    bucket=settings.influxdb_bucket,
                    record=batch,
                    data_frame_measurement_name=measurement,
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

    def read_data_in_range(self, measurement: str, start_date: str, end_date: str) -> pd.DataFrame:
        query_api = db_manager.get_query_api()
        if not query_api:
            logger.error(f"API de consulta do InfluxDB indisponível ao ler range para '{measurement}'.")
            return pd.DataFrame()
        logger.debug(f"Lendo dados de '{measurement}' de {start_date} a {end_date}")
        try:
            query = f'''
            from(bucket:"{settings.influxdb_bucket}") 
                |> range(start: {start_date}, stop: {end_date}) 
                |> filter(fn: (r) => r._measurement == "{measurement}") 
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            df = query_api.query_data_frame(query)
            if df.empty: return pd.DataFrame()
            df = df.rename(columns={"_time": "timestamp"})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            return df.drop(columns=[col for col in ['result', 'table'] if col in df.columns])
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

    def run_btc_pipeline(self, symbol: str, interval: str = '1m'):
        measurement_name = f"btc_{symbol.lower().replace('/', '_')}_{interval}"
        end_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
        last_timestamp_in_db = self._query_last_timestamp(measurement_name)
        if not last_timestamp_in_db:
            logger.info(f"Nenhum dado encontrado para '{measurement_name}'. Iniciando bootstrap.")
            df_ohlcv_history = pd.DataFrame()
            csv_path = settings.data_paths.historical_data_file
            if not os.path.exists(csv_path): csv_path = settings.data_paths.kaggle_bootstrap_file
            if os.path.exists(csv_path):
                logger.info(f"Carregando histórico de '{csv_path}'...")
                df_csv = pd.read_csv(csv_path, low_memory=False, on_bad_lines='skip')
                df_ohlcv_history = self._preprocess_kaggle_data(df_csv)
            if not df_ohlcv_history.empty:
                logger.info(f"{len(df_ohlcv_history)} velas históricas carregadas. Escrevendo no DB...")
                df_ohlcv_history['taker_buy_volume'] = 0.0
                df_ohlcv_history['taker_sell_volume'] = 0.0
                df_to_db = df_ohlcv_history[df_ohlcv_history.index >= '2018-01-01']
                self._write_dataframe_to_influx(df_to_db, measurement_name)
                logger.info("Iniciando backfill de Order Flow do último ano...")
                one_year_ago = df_to_db.index.max() - pd.Timedelta(days=365)
                backfill_start_date = max(one_year_ago, df_to_db.index.min())
                backfill_end_date = df_to_db.index.max()
                if self.binance_client and backfill_start_date < backfill_end_date:
                    df_orderflow_backfill = self._get_historical_agg_trades(symbol, backfill_start_date, backfill_end_date)
                    if not df_orderflow_backfill.empty:
                        logger.info(f"{len(df_orderflow_backfill)} registos de Order Flow encontrados para o backfill.")
                        self._write_dataframe_to_influx(df_orderflow_backfill, measurement_name)
                        logger.info("✅ Backfill de Order Flow concluído.")
                    else:
                        logger.warning("Nenhum dado de Order Flow encontrado para o período de backfill.")
            else:
                logger.error("Nenhum ficheiro de histórico encontrado. Bootstrap impossível.")
                return
            last_timestamp_in_db = self._query_last_timestamp(measurement_name)
        if not last_timestamp_in_db:
            logger.error("Falha ao obter timestamp após bootstrap.")
            return
        start_utc = last_timestamp_in_db + pd.Timedelta(minutes=1)
        if self.binance_client and start_utc < end_utc:
            logger.info(f"Buscando novos dados de BTC de {start_utc.strftime('%Y-%m-%d %H:%M:%S')} até {end_utc.strftime('%Y-%m-%d %H:%M:%S')}...")
            df_ohlcv_new = self._get_historical_klines_binance(symbol, interval, start_utc, end_utc)
            df_orderflow_new = self._get_historical_agg_trades(symbol, start_utc, end_utc)
            if not df_ohlcv_new.empty:
                df_combined = df_ohlcv_new.join(df_orderflow_new, how='left').fillna(0)
                self._write_dataframe_to_influx(df_combined, measurement_name)
        else:
            logger.info("Dados de BTC no DB já estão atualizados ou cliente offline.")

    def run_macro_pipeline(self):
        """
        Busca e atualiza dados macroeconômicos do Yahoo Finance, usando CSVs como
        cache local resiliente antes de escrever no banco de dados.
        """
        logger.info("--- 🌐 INICIANDO PIPELINE DE DADOS MACRO (FONTE: YFINANCE) 🌐 ---")
        macro_assets = {
            "dxy": {"ticker": "DX-Y.NYB", "path": os.path.join(settings.data_paths.macro_data_dir, "DXY.csv")},
            "vix": {"ticker": "^VIX", "path": os.path.join(settings.data_paths.macro_data_dir, "VIX.csv")},
            "gold": {"ticker": "GC=F", "path": os.path.join(settings.data_paths.macro_data_dir, "GOLD.csv")},
            "tnx": {"ticker": "^TNX", "path": os.path.join(settings.data_paths.macro_data_dir, "TNX.csv")},
            "spx": {"ticker": "^GSPC", "path": os.path.join(settings.data_paths.macro_data_dir, "SPX.csv")},
            "ndx": {"ticker": "^IXIC", "path": os.path.join(settings.data_paths.macro_data_dir, "NDX.csv")},
            "uso": {"ticker": "USO", "path": os.path.join(settings.data_paths.macro_data_dir, "USO.csv")}
        }

        os.makedirs(settings.data_paths.macro_data_dir, exist_ok=True)
        all_macro_data_for_db = []

        for name, asset_info in macro_assets.items():
            logger.info(f"Processando ativo macro: {name.upper()}")
            historical_data = pd.DataFrame()
            
            try:
                if os.path.exists(asset_info["path"]):
                    logger.debug(f"Ficheiro CSV encontrado para {name.upper()}. Lendo dados históricos.")
                    temp_df = pd.read_csv(asset_info["path"], index_col='date', parse_dates=True)
                    if temp_df.index.tz is None:
                        temp_df.index = temp_df.index.tz_localize('UTC')
                    else:
                        temp_df.index = temp_df.index.tz_convert('UTC')
                    historical_data = temp_df
            except Exception as e:
                logger.warning(f"Não foi possível ler o CSV {asset_info['path']}. Ele será recriado do zero. Erro: {e}")

            start_date_for_download = (historical_data.index.max() + pd.Timedelta(days=1)) if not historical_data.empty else pd.to_datetime('2018-01-01', utc=True)
            end_date_for_download = pd.to_datetime(datetime.date.today() + datetime.timedelta(days=1), utc=True)

            new_data = pd.DataFrame()
            if start_date_for_download < end_date_for_download:
                logger.info(f"Buscando dados para {name.upper()} de {start_date_for_download.date()} até {end_date_for_download.date()}.")
                try:
                    # --- CORREÇÃO CRÍTICA FINAL ---
                    # Removido o parâmetro 'group_by' para evitar colunas multi-nível indesejadas
                    new_data = yf.download(asset_info["ticker"], 
                                        start=start_date_for_download, 
                                        end=end_date_for_download, 
                                        progress=False,
                                        auto_adjust=False)
                    if not new_data.empty:
                        if new_data.index.tz is None:
                            new_data.index = new_data.index.tz_localize('UTC')
                        else:
                            new_data.index = new_data.index.tz_convert('UTC')
                        logger.info(f"✅ {len(new_data)} novos registos baixados para {name.upper()}.")
                    else:
                        logger.info(f"Nenhum dado novo encontrado para {name.upper()} no período solicitado.")

                except Exception as e:
                    logger.error(f"❌ Falha no download de dados para {name.upper()} via yfinance: {e}")
            else:
                logger.info(f"Dados para {name.upper()} já estão atualizados. Nenhum download necessário.")

            combined_data = pd.concat([historical_data, new_data])
            combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
            combined_data.sort_index(inplace=True)
            
            if not combined_data.empty:
                combined_data.columns = [(col[0] if isinstance(col, tuple) else col).lower() for col in combined_data.columns]
                
                if 'adj close' in combined_data.columns:
                    combined_data.drop(columns=['adj close'], inplace=True)
                if 'volume' not in combined_data.columns: 
                    combined_data['volume'] = 0

                # Para depuração, caso o erro persista (o que é improvável agora):
                # logger.debug(f"Colunas de {name.upper()} após limpeza: {combined_data.columns.tolist()}")

                final_cols = ['open', 'high', 'low', 'close', 'volume']
                data_to_save = combined_data[final_cols]
                data_to_save.index.name = 'date'
                data_to_save.to_csv(asset_info["path"])
                logger.debug(f"CSV para {name.upper()} salvo/atualizado com sucesso em {asset_info['path']}.")
                
                data_for_db = data_to_save.copy()
                data_for_db.columns = [f"{name}_{col.lower()}" for col in data_for_db.columns]
                all_macro_data_for_db.append(data_for_db)
            else:
                logger.warning(f"Nenhum dado (nem histórico, nem novo) disponível para {name.upper()}.")

        if all_macro_data_for_db:
            logger.info("Combinando todos os dados macro para escrita no banco de dados...")
            df_macro_combined = pd.concat(all_macro_data_for_db, axis=1)
            # Preenche para a frente os valores em dias não úteis (finais de semana, feriados)
            df_macro_combined.ffill(inplace=True) 
            df_macro_combined.dropna(how='all', inplace=True) # Remove linhas onde todos os dados são nulos
            
            # Reamostra para 1 minuto para corresponder aos dados de BTC
            df_macro_combined_resampled = df_macro_combined.resample('1min').ffill()
            df_macro_combined_resampled.index.name = 'timestamp'
            
            # --- MELHORIA DE PERFORMANCE CRÍTICA ---
            # 1. Verifica qual é o último registro já salvo no banco de dados.
            measurement_name = "macro_data_1m"
            last_ts_in_db = self._query_last_timestamp(measurement_name)
            
            df_to_write = df_macro_combined_resampled # Por padrão, escreve tudo
            
            if last_ts_in_db:
                logger.info(f"Último registro macro no DB é de {last_ts_in_db}. Filtrando para enviar apenas dados novos.")
                # 2. Filtra o DataFrame para pegar apenas as linhas MAIORES (mais recentes) que o último registro.
                df_to_write = df_macro_combined_resampled[df_macro_combined_resampled.index > last_ts_in_db]
            else:
                logger.info("Nenhum dado macro encontrado no DB. Preparando para escrever todo o histórico.")

            logger.info(f"Dados macro combinados e reamostrados. Preparando para escrever {len(df_to_write)} registos no DB...")
            self._write_dataframe_to_influx(df_to_write, measurement_name)
        else:
            logger.warning("Nenhum dado macro foi processado para ser enviado ao banco de dados.")

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

    def run_full_pipeline(self):
        """
        Executa o pipeline completo em LOTES MENSAIS para otimizar o uso de memória.
        """
        # FASE 1: Ingestão de dados brutos
        self.run_btc_pipeline(symbol='BTCUSDT', interval='1m')
        self.run_macro_pipeline()

        # FASE 2: Processamento em "Streaming" (Mês a Mês)
        logger.info("--- 🔄 INICIANDO PROCESSAMENTO DA TABELA MESTRE EM LOTES MENSAIS 🔄 ---")

        start_date = pd.to_datetime('2018-01-01', utc=True)
        end_date = pd.to_datetime(datetime.date.today() + datetime.timedelta(days=1), utc=True)
        
        current_date = start_date
        total_months = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month
        pbar = tqdm(total=total_months, desc="Processando Tabela Mestre")

        while current_date < end_date:
            chunk_start = current_date.isoformat()
            chunk_end = (current_date + relativedelta(months=1)).isoformat()
            
            logger.debug(f"Processando lote de {current_date.strftime('%Y-%m')}...")

            df_btc_chunk = self.read_data_in_range("btc_btcusdt_1m", chunk_start, chunk_end)
            df_macro_chunk = self.read_data_in_range("macro_data_1m", chunk_start, chunk_end)

            if df_btc_chunk.empty:
                logger.debug(f"Nenhum dado de BTC para o período {current_date.strftime('%Y-%m')}. A saltar.")
                current_date += relativedelta(months=1)
                pbar.update(1)
                continue

            df_combined = df_btc_chunk.join(df_macro_chunk, how='left').ffill()
            df_final_features = add_all_features(df_combined)

            if self.validate_data(df_final_features):
                self._write_dataframe_to_influx(df_final_features, "features_master_table")
            else:
                logger.error(f"Validação falhou para o lote {current_date.strftime('%Y-%m')}. Este lote não será salvo.")
            
            del df_btc_chunk, df_macro_chunk, df_combined, df_final_features
            gc.collect()

            current_date += relativedelta(months=1)
            pbar.update(1)
        
        pbar.close()
        logger.info("🎉🎉🎉 PIPELINE INDUSTRIAL CONCLUÍDO! A FONTE DA VERDADE ESTÁ PRONTA. 🎉🎉🎉")

if __name__ == '__main__':
    pipeline = DataPipeline()
    pipeline.run_full_pipeline()