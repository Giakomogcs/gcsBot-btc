# src/core/feature_engineering.py
import pandas as pd
import numpy as np
import pandas_ta as ta

import yfinance as yf
import os
import sys

# Resolução de Path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logger import logger
from src.config_manager import settings

def add_macro_economic_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Carrega, atualiza e integra dados macroeconómicos ao DataFrame principal.
    """
    logger.info("Iniciando pipeline de dados macroeconómicos...")
    df_result = df.copy()

    macro_assets = {
        "dxy": {"ticker": "DX-Y.NYB", "path": os.path.join(settings.data_paths.data_dir, "macro", "DXY.csv")},
        "vix": {"ticker": "^VIX", "path": os.path.join(settings.data_paths.data_dir, "macro", "VIX.csv")},
        "gold": {"ticker": "GC=F", "path": os.path.join(settings.data_paths.data_dir, "macro", "GOLD.csv")},
        "tnx": {"ticker": "^TNX", "path": os.path.join(settings.data_paths.data_dir, "macro", "TNX.csv")},
        "spx": {"ticker": "^GSPC", "path": os.path.join(settings.data_paths.data_dir, "macro", "SPX.csv")},
        "ndx": {"ticker": "^IXIC", "path": os.path.join(settings.data_paths.data_dir, "macro", "NDX.csv")},
        "uso": {"ticker": "USO", "path": os.path.join(settings.data_paths.data_dir, "macro", "USO.csv")}
    }
    
    os.makedirs(os.path.join(settings.data_paths.data_dir, "macro"), exist_ok=True)
    STANDARD_COLUMNS = ['open', 'high', 'low', 'close', 'volume']

    for name, asset_info in macro_assets.items():
        try:
            logger.debug(f"Processando ativo macro: {name.upper()}")
            historical_data = pd.DataFrame()
            if os.path.exists(asset_info["path"]):
                try:
                    historical_data = pd.read_csv(asset_info["path"], index_col='date', parse_dates=True)
                    historical_data.columns = [col.lower() for col in historical_data.columns]
                except Exception:
                    logger.warning(f"Não foi possível ler {asset_info['path']}. Ficheiro será recriado.")

            last_date = historical_data.index.max() if not historical_data.empty else pd.to_datetime('2018-01-01', utc=True)
            start_update = last_date + pd.Timedelta(days=1)
            today = pd.Timestamp.now(tz='UTC')

            if start_update <= today:
                new_data = yf.download(asset_info["ticker"], start=start_update, end=today, progress=False)
                if not new_data.empty:
                    new_data.rename(columns=str.lower, inplace=True)
                    combined_data = pd.concat([historical_data, new_data])
                    combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                    final_data_to_save = combined_data[[col for col in STANDARD_COLUMNS if col in combined_data.columns]]
                    final_data_to_save.index.name = 'date'
                    final_data_to_save.to_csv(asset_info["path"])
                    final_asset_data = final_data_to_save
                else:
                    final_asset_data = historical_data
            else:
                final_asset_data = historical_data

            if final_asset_data.empty:
                raise ValueError(f"Nenhum dado para {name.upper()}")

            macro_resampled = final_asset_data['close'].resample('1min').ffill()
            df_result[f'{name}_close_change'] = macro_resampled.pct_change(fill_method=None)

        except Exception as e:
            logger.error(f"Falha ao processar dados para {name.upper()}: {e}")
            df_result[f'{name}_close_change'] = 0.0

    logger.info("Calculando correlações macro...")
    if 'close' in df_result.columns:
        for name in macro_assets.keys():
            col_name = f'{name}_close_change'
            corr_col_name = f'btc_{name}_corr_30d'
            if col_name in df_result.columns:
                 df_result[corr_col_name] = df_result['close'].rolling(window=30*1440).corr(df_result[col_name])
    
    logger.info("✅ Pipeline de dados macroeconómicos concluído.")
    return df_result

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Calculando indicadores técnicos...")
    df = df.sort_index()

    # Anexa todos os indicadores usando a extensão 'ta' do pandas_ta
    df.ta.atr(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.macd(append=True)
    df.ta.adx(length=14, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.stoch(append=True)
    df.ta.cci(length=20, append=True)
    df.ta.willr(length=14, append=True)

    # Renomeia colunas para corresponder aos nomes originais e calcula features derivadas
    df.rename(columns={
        'ATRr_14': 'atr',
        'BBL_20_2.0': 'bb_lower',
        'BBM_20_2.0': 'bb_middle',
        'BBU_20_2.0': 'bb_upper',
        'BBB_20_2.0': 'bb_width', # Bollinger Band Width
        'BBP_20_2.0': 'bb_pband', # Bollinger Band Percentage
        'MACD_12_26_9': 'macd',
        'MACDh_12_26_9': 'macd_hist',
        'MACDs_12_26_9': 'macd_signal',
        'ADX_14': 'adx',
        'DMP_14': 'adx_pos',
        'DMN_14': 'adx_neg',
        'RSI_14': 'rsi',
        'STOCHk_14_3_3': 'stoch_k',
        'STOCHd_14_3_3': 'stoch_d',
        'WILLR_14': 'williams_r',
        'CCI_20_0.015': 'cci'
    }, inplace=True)

    # Calcula as features que dependem dos indicadores base
    df['adx_power'] = df['adx_pos'] - df['adx_neg']
    df['stoch_osc'] = df['stoch_k'] # O oscilador estocástico é a linha %K
    df['price_change_1m'] = df['close'].pct_change(1)
    df['price_change_5m'] = df['close'].pct_change(5)
    df['momentum_10m'] = df['close'].pct_change(10)
    
    atr_short = df['atr'].rolling(window=5).mean()
    atr_long = df['atr'].rolling(window=100).mean()
    df['volatility_ratio'] = atr_short / (atr_long + 1e-10)

    # O 'macd_diff' original é o histograma no pandas-ta
    if 'macd_hist' in df.columns:
        df.rename(columns={'macd_hist': 'macd_diff'}, inplace=True)
    
    # Remove colunas auxiliares se não forem necessárias
    # df.drop(columns=[...], inplace=True)
    
    return df

def add_order_flow_features(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Calculando features de Fluxo de Ordens (CVD)...")
    df['volume_delta'] = df['taker_buy_volume'] - df['taker_sell_volume']
    df['cvd'] = df['volume_delta'].cumsum()
    df['cvd_short_term'] = df['volume_delta'].rolling(window=20).sum()
    return df


def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Função central que adiciona todas as features, garantindo nomes consistentes e previsíveis
    para honrar o "contrato" definido no config.yml.
    """
    logger.debug("Iniciando a adição de todas as features de engenharia...")
    df_copy = df.copy()

    required_cols = ['open', 'high', 'low', 'close', 'volume']
    if not all(col in df_copy.columns for col in required_cols):
        logger.error(f"DataFrame de entrada para 'add_all_features' não contém as colunas necessárias: {required_cols}")
        return df_copy

    # --- INÍCIO DO BLOCO DE DEPURAÇÃO ---
    logger.debug("Calculando RSI...")
    df_copy.ta.rsi(length=14, append=True, col_names=('rsi_14',))
    logger.info(f"Coluna 'rsi_14' existe? {'rsi_14' in df_copy.columns}")

    logger.debug("Calculando MACD...")
    df_copy.ta.macd(fast=12, slow=26, signal=9, append=True, col_names=('macd_12_26_9', 'macd_hist_12_26_9', 'macd_signal_12_26_9'))
    logger.info(f"Coluna 'macd_hist_12_26_9' existe? {'macd_hist_12_26_9' in df_copy.columns}")

    logger.debug("Calculando ATR...")
    df_copy.ta.atr(length=14, append=True, col_names=('atr_14',))
    logger.info(f"Coluna 'atr_14' existe? {'atr_14' in df_copy.columns}")
    # --- FIM DO BLOCO DE DEPURAÇÃO ---
    
    df_copy.ta.bbands(length=20, std=2, append=True, col_names=('bbl_20_2.0', 'bbm_20_2.0', 'bbu_20_2.0', 'bbb_20_2.0', 'bbp_20_2.0'))

    if 'macd_hist_12_26_9' in df_copy.columns:
        df_copy.rename(columns={'macd_hist_12_26_9': 'macd_diff_12_26_9'}, inplace=True)
        logger.info(f"Coluna 'macd_diff_12_26_9' existe? {'macd_diff_12_26_9' in df_copy.columns}")
    
    df_copy.columns = [str(col).lower().replace('-', '_').replace(' ', '_').replace('.', '_') for col in df_copy.columns]
    
    if 'taker_buy_volume' not in df_copy.columns: df_copy['taker_buy_volume'] = 0.0
    if 'taker_sell_volume' not in df_copy.columns: df_copy['taker_sell_volume'] = 0.0
    df_copy['volume_delta'] = df_copy['taker_buy_volume'] - df_copy['taker_sell_volume']
    df_copy['cvd'] = df_copy['volume_delta'].cumsum()

    if 'funding_rate' in df_copy.columns:
        df_copy['funding_rate_mean_24h'] = df_copy['funding_rate'].rolling(window=1440).mean()
    if 'open_interest' in df_copy.columns:
        df_copy['open_interest_pct_change_4h'] = df_copy['open_interest'].pct_change(periods=240)
    if 'fear_and_greed' in df_copy.columns:
        df_copy['fng_change_3d'] = df_copy['fear_and_greed'].diff(periods=1440*3)

    df_copy['btc_returns'] = df_copy['close'].pct_change(periods=1440)
    macro_assets = ["dxy", "vix", "gold", "tnx", "spx", "ndx", "uso"]
    for asset in macro_assets:
        close_col = f"{asset}_close"
        if close_col in df_copy.columns:
            asset_returns = df_copy[close_col].pct_change(periods=1440)
            corr_col_name = f"btc_{asset}_corr_30d"
            df_copy[corr_col_name] = df_copy['btc_returns'].rolling(window=43200).corr(asset_returns)

    df_copy.drop(columns=['btc_returns'], inplace=True, errors='ignore')
    
    logger.debug("✅ Adição de features de engenharia concluída.")
    return df_copy