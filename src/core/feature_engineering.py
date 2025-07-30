# src/core/feature_engineering.py
import pandas as pd
import numpy as np
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator, CCIIndicator
from ta.momentum import StochasticOscillator, RSIIndicator, WilliamsRIndicator
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
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    bb = BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_width'] = bb.bollinger_wband()
    df['bb_pband'] = bb.bollinger_pband()
    macd = MACD(close=df['close'])
    df['macd_diff'] = macd.macd_diff()
    adx = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['adx'] = adx.adx()
    df['adx_power'] = adx.adx_pos() - adx.adx_neg()
    df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
    df['stoch_osc'] = StochasticOscillator(high=df['high'], low=df['low'], close=df['close']).stoch()
    df['price_change_1m'] = df['close'].pct_change(1, fill_method=None)
    df['price_change_5m'] = df['close'].pct_change(5, fill_method=None)
    df['momentum_10m'] = df['close'].pct_change(10, fill_method=None)
    atr_short = df['atr'].rolling(window=5).mean()
    atr_long = df['atr'].rolling(window=100).mean()
    df['volatility_ratio'] = atr_short / (atr_long + 1e-10) 
    df['cci'] = CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()
    df['williams_r'] = WilliamsRIndicator(high=df['high'], low=df['low'], close=df['close'], lbp=14).williams_r()
    return df

def add_order_flow_features(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Calculando features de Fluxo de Ordens (CVD)...")
    df['volume_delta'] = df['taker_buy_volume'] - df['taker_sell_volume']
    df['cvd'] = df['volume_delta'].cumsum()
    df['cvd_short_term'] = df['volume_delta'].rolling(window=20).sum()
    return df

def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Função principal que aplica todas as etapas de engenharia de features.
    """
    df_with_features = df.copy()
    
    df_with_features = add_technical_indicators(df_with_features)
    df_with_features = add_order_flow_features(df_with_features)
    df_with_features = add_macro_economic_features(df_with_features)
    
    logger.info("Limpando e preenchendo valores nulos restantes...")
    df_with_features = df_with_features.bfill().ffill()
    df_with_features.fillna(0, inplace=True)
    
    logger.info("✅ Engenharia de features concluída.")
    return df_with_features