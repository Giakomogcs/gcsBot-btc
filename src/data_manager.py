# src/data_manager.py (VERSÃO 3.1 - FINAL POLIDO)

import os
import datetime
import time
import pandas as pd
import numpy as np
import yfinance as yf
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from tqdm import tqdm

from src.logger import logger
from src.config import (
    API_KEY, API_SECRET, USE_TESTNET, HISTORICAL_DATA_FILE, KAGGLE_BOOTSTRAP_FILE,
    FORCE_OFFLINE_MODE, COMBINED_DATA_CACHE_FILE
)

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

class DataManager:
    def __init__(self):
        self.client = None
        if not FORCE_OFFLINE_MODE:
            try:
                self.client = Client(API_KEY, API_SECRET, tld='com', testnet=USE_TESTNET, requests_params={"timeout": 30})
                self.client.ping()
                logger.info("Cliente Binance inicializado e conexão com a API confirmada.")
            except (BinanceAPIException, BinanceRequestException, Exception) as e:
                logger.warning(f"FALHA NA CONEXÃO: {e}. O bot operará em modo OFFLINE-FALLBACK.")
                self.client = None
        else:
            logger.info("MODO OFFLINE FORÇADO está ativo.")

    def _fetch_and_update_macro_data(self, caminho_dados: str = 'data/macro'):
        logger.info("Iniciando verificação e atualização dos dados macro...")
        ticker_map = {'dxy': 'DX-Y.NYB', 'gold': 'GC=F', 'tnx': '^TNX', 'vix': '^VIX'}
        os.makedirs(caminho_dados, exist_ok=True)

        for nome_ativo, ticker in ticker_map.items():
            caminho_arquivo = os.path.join(caminho_dados, f'{nome_ativo}.csv')
            try:
                start_fetch_date = '2017-01-01'
                existing_df = None
                if os.path.exists(caminho_arquivo):
                    try:
                        existing_df = pd.read_csv(caminho_arquivo, index_col='Date', parse_dates=True)
                        if not existing_df.empty:
                            last_date = existing_df.index.max()
                            start_fetch_date = last_date + datetime.timedelta(days=1)
                    except Exception as e:
                        logger.warning(f"Não foi possível ler o arquivo existente para '{nome_ativo}': {e}. Ele será recriado.")
                        existing_df = None

                end_fetch_date = datetime.datetime.now(datetime.timezone.utc)
                if isinstance(start_fetch_date, (datetime.datetime, pd.Timestamp)) and start_fetch_date.date() >= end_fetch_date.date():
                    logger.info(f"Dados macro para '{nome_ativo}' já estão atualizados.")
                    continue
                
                logger.info(f"Baixando dados para '{nome_ativo}' de {start_fetch_date if isinstance(start_fetch_date, str) else start_fetch_date.strftime('%Y-%m-%d')} até hoje...")
                df_downloaded = yf.download(ticker, start=start_fetch_date, end=end_fetch_date, progress=False, auto_adjust=True)
                
                if df_downloaded.empty:
                    logger.info(f"Nenhum dado novo encontrado para '{nome_ativo}'.")
                    continue
                
                clean_df = df_downloaded[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                clean_df.index.name = 'Date'
                
                if existing_df is not None:
                    clean_df.to_csv(caminho_arquivo, mode='a', header=False)
                else:
                    clean_df.to_csv(caminho_arquivo)
                time.sleep(1)
            except Exception as e:
                logger.error(f"Falha ao buscar ou salvar dados para o ativo '{nome_ativo}': {e}", exc_info=True)
        logger.info("Verificação de dados macro concluída.")

    def _load_and_unify_local_macro_data(self, caminho_dados: str = 'data/macro') -> pd.DataFrame:
        logger.info("Padronizando e unificando dados macro locais...")
        nomes_ativos = ['dxy', 'gold', 'tnx', 'vix']
        lista_dataframes = []
        for nome_ativo in nomes_ativos:
            caminho_arquivo = os.path.join(caminho_dados, f'{nome_ativo}.csv')
            if not os.path.exists(caminho_arquivo):
                logger.warning(f"AVISO: Arquivo macro '{caminho_arquivo}' não encontrado. Pulando.")
                continue
            try:
                df = pd.read_csv(caminho_arquivo, index_col='Date', parse_dates=True)
                if df.index.tz is None: df.index = df.index.tz_localize('UTC')
                else: df.index = df.index.tz_convert('UTC')
                if 'Close' in df.columns:
                    df = df[['Close']].copy()
                    df.rename(columns={'Close': f'{nome_ativo}_close'}, inplace=True)
                    lista_dataframes.append(df)
            except Exception as e:
                logger.error(f"ERRO ao processar o arquivo macro '{caminho_arquivo}': {e}", exc_info=True)
        if not lista_dataframes:
            logger.warning("Nenhum dado macro foi processado.")
            return pd.DataFrame()
        df_final = pd.concat(lista_dataframes, axis=1, join='outer')
        df_final.sort_index(inplace=True); df_final.ffill(inplace=True); df_final.dropna(how='all', inplace=True)
        logger.info("Dados macro locais unificados com sucesso.")
        return df_final
        
    def get_historical_data_by_batch(self, symbol, interval, start_date_dt, end_date_dt):
        all_dfs = []
        total_days = max(1, (end_date_dt - start_date_dt).days)
        progress_bar = tqdm(total=total_days, desc=f"Baixando dados de {symbol}", unit="d", leave=False)
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

    def _fetch_and_manage_btc_data(self, symbol, interval='1m'):
        end_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
        if os.path.exists(HISTORICAL_DATA_FILE):
            logger.info(f"Arquivo de dados local do BTC encontrado em '{HISTORICAL_DATA_FILE}'. Carregando...")
            df = pd.read_csv(HISTORICAL_DATA_FILE, index_col=0, parse_dates=True); df.index = pd.to_datetime(df.index, utc=True)
            if self.client:
                last_timestamp = df.index.max().to_pydatetime()
                if last_timestamp < end_utc:
                    logger.info("Dados locais do BTC estão desatualizados. Buscando novos dados da Binance...")
                    try:
                        df_new = self.get_historical_data_by_batch(symbol, interval, last_timestamp + datetime.timedelta(minutes=1), end_utc)
                        if not df_new.empty:
                            df = pd.concat([df, df_new]); df = df.loc[~df.index.duplicated(keep='last')]; df.sort_index(inplace=True)
                            df.to_csv(HISTORICAL_DATA_FILE); logger.info(f"SUCESSO: Arquivo de dados do BTC atualizado com {len(df_new)} novas velas.")
                    except Exception as e: logger.warning(f"FALHA NA ATUALIZAÇÃO DO BTC: {e}. Continuando com dados locais.")
            return df
        if os.path.exists(KAGGLE_BOOTSTRAP_FILE):
            logger.info(f"Arquivo mestre do BTC não encontrado. Iniciando a partir do arquivo Kaggle: '{KAGGLE_BOOTSTRAP_FILE}'")
            df_kaggle = pd.read_csv(KAGGLE_BOOTSTRAP_FILE, low_memory=False, on_bad_lines='skip')
            df = self._preprocess_kaggle_data(df_kaggle)
            last_timestamp = df.index.max().to_pydatetime()
            if self.client and last_timestamp < end_utc:
                logger.info("Atualizando dados do Kaggle com os dados mais recentes da Binance...")
                try:
                    df_new = self.get_historical_data_by_batch(symbol, interval, last_timestamp + datetime.timedelta(minutes=1), end_utc)
                    if not df_new.empty:
                        df = pd.concat([df, df_new]); df = df.loc[~df.index.duplicated(keep='last')]; df.sort_index(inplace=True)
                except Exception as e: logger.warning(f"FALHA NA ATUALIZAÇÃO DO BTC: {e}. Continuando com dados do Kaggle.")
            logger.info(f"Salvando o novo arquivo de dados mestre do BTC em '{HISTORICAL_DATA_FILE}'."); df.to_csv(HISTORICAL_DATA_FILE)
            return df
        if self.client:
            logger.warning("Nenhum arquivo local do BTC encontrado. Baixando o último ano da Binance como fallback.")
            start_utc = end_utc - datetime.timedelta(days=365); df = self.get_historical_data_by_batch(symbol, interval, start_utc, end_utc)
            if not df.empty: df.to_csv(HISTORICAL_DATA_FILE)
            return df
        logger.error("Nenhum arquivo de dados local do BTC encontrado e o bot está em modo offline. Não é possível continuar.")
        return pd.DataFrame()
        
    def _add_market_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Calculando regimes de mercado (Camada 1)...")
        if df.empty or 'close' not in df.columns:
            logger.warning("DataFrame vazio ou sem coluna 'close'. Não é possível calcular regimes."); df['market_regime'] = 'INDETERMINADO'
            return df
        df_daily = df['close'].resample('D').last()
        sma_50d = df_daily.rolling(window=50).mean(); sma_200d = df_daily.rolling(window=200).mean()
        regime_df = pd.DataFrame({'daily_close': df_daily, 'sma_50d': sma_50d, 'sma_200d': sma_200d})
        conditions = [
            (regime_df['daily_close'] > regime_df['sma_50d']) & (regime_df['sma_50d'] > regime_df['sma_200d']),
            (regime_df['daily_close'] > regime_df['sma_200d']) & (regime_df['daily_close'] < regime_df['sma_50d']),
            (regime_df['daily_close'] < regime_df['sma_200d'])]
        outcomes = ['BULL_FORTE', 'RECUPERACAO', 'BEAR']
        regime_df['market_regime'] = np.select(conditions, outcomes, default='LATERAL')

        df['market_regime'] = regime_df['market_regime'].reindex(df.index, method='ffill')
        df['market_regime'] = df['market_regime'].bfill() # Usar a atribuição direta

        logger.info("Regimes de mercado calculados e adicionados ao DataFrame.")
        return df

    def update_and_load_data(self, symbol, interval='1m'):
        if not FORCE_OFFLINE_MODE:
            self._fetch_and_update_macro_data()
        df_btc = self._fetch_and_manage_btc_data(symbol, interval)
        if df_btc.empty: return pd.DataFrame()
        last_btc_timestamp = df_btc.index.max()
        if os.path.exists(COMBINED_DATA_CACHE_FILE):
            logger.info(f"Arquivo de cache encontrado em '{COMBINED_DATA_CACHE_FILE}'. Verificando se está atualizado...")
            df_cache = pd.read_csv(COMBINED_DATA_CACHE_FILE, index_col=0, parse_dates=True, dtype={'market_regime': 'category'})
            df_cache.index = pd.to_datetime(df_cache.index, utc=True)
            if not df_cache.empty and df_cache.index.max() == last_btc_timestamp:
                logger.info("✅ Cache está atualizado! Carregando dados unificados diretamente do cache.")
                return _optimize_memory_usage(df_cache)
            else:
                logger.info("Cache está desatualizado. Reconstruindo...")
        logger.info("Iniciando processo de unificação de dados (cache não disponível ou obsoleto).")
        df_macro = self._load_and_unify_local_macro_data()
        if not df_macro.empty:
            logger.info("Combinando dados do BTC com dados macro unificados...")
            df_combined = df_btc.join(df_macro, how='left')
        else:
            df_combined = df_btc
        macro_cols = [col for col in df_combined.columns if '_close' in col]
        df_combined[macro_cols] = df_combined[macro_cols].ffill()
        df_combined = self._add_market_regime(df_combined)
        df_combined = _optimize_memory_usage(df_combined)
        logger.info(f"Salvando dados unificados e otimizados no arquivo de cache: '{COMBINED_DATA_CACHE_FILE}'")
        df_combined.to_csv(COMBINED_DATA_CACHE_FILE)
        logger.info("Processo de coleta e combinação de dados concluído.")
        return df_combined

    def _preprocess_kaggle_data(self, df_kaggle: pd.DataFrame) -> pd.DataFrame:
        logger.info("Pré-processando dados do Kaggle...")
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
        logger.info(f"Processamento do Kaggle concluído. {len(df)} registros válidos carregados.")
        return df
