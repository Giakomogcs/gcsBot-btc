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