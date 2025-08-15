# jules_bot/bot/feature_engineering.py (VERSÃO FINAL E FLEXÍVEL)

import sys
import pandas as pd
import numpy as np
import pandas_ta as ta
from tqdm import tqdm

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager

def add_all_features(df: pd.DataFrame, live_mode: bool = False) -> pd.DataFrame:
    """
    Função central que adiciona todas as features.
    :param df: DataFrame com os dados brutos.
    :param live_mode: Se True, não calcula o 'target', que só é usado para treino.
    """
    logger.debug(f"Iniciando a adição de features (Modo Live: {live_mode})...")
    df_copy = df.copy()

    # --- GARANTIA DE DADOS DE ENTRADA ---
    ohlc_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in ohlc_cols:
        if col in df_copy.columns:
            df_copy[col] = pd.to_numeric(df_copy[col], errors='coerce')
    df_copy.dropna(subset=ohlc_cols, inplace=True)

    if df_copy.empty:
        logger.error("DataFrame vazio após limpeza de OHLC. Abortando features.")
        return pd.DataFrame()

    # --- 1. INDICADORES TÉCNICOS ---
    logger.debug("Calculando indicadores técnicos...")
    df_copy.ta.rsi(length=14, append=True, col_names=('rsi_14',))
    df_copy.ta.macd(fast=12, slow=26, signal=9, append=True, col_names=('macd_12_26_9', 'macd_hist_12_26_9', 'macd_signal_12_26_9'))
    df_copy.ta.atr(length=14, append=True, col_names=('atr_14',))
    df_copy.ta.bbands(length=20, std=2, append=True, col_names=('bbl_20_2_0', 'bbm_20_2_0', 'bbu_20_2_0', 'bbb_20_2_0', 'bbp_20_2_0'))
    df_copy.ta.ema(length=20, append=True, col_names=('ema_20',))
    df_copy.ta.ema(length=100, append=True, col_names=('ema_100',))
    df_copy.ta.ema(length=200, append=True, col_names=('ema_200',))
    if 'macd_hist_12_26_9' in df_copy.columns:
        df_copy.rename(columns={'macd_hist_12_26_9': 'macd_diff_12_26_9'}, inplace=True)

    # --- 2. FEATURES DE FLUXO DE ORDENS ---
    logger.debug("Calculando features de fluxo de ordens...")
    if 'taker_buy_volume' not in df_copy.columns: df_copy['taker_buy_volume'] = 0.0
    if 'taker_sell_volume' not in df_copy.columns: df_copy['taker_sell_volume'] = 0.0
    df_copy['volume_delta'] = df_copy['taker_buy_volume'] - df_copy['taker_sell_volume']
    df_copy['cvd'] = df_copy['volume_delta'].cumsum()
    
    # --- 3. FEATURES DE SENTIMENTO E DERIVATIVOS ---
    logger.debug("Calculando features de Sentimento e Derivativos...")
    if 'fear_and_greed' in df_copy.columns:
        df_copy['fng_change_3d'] = df_copy['fear_and_greed'].diff(periods=3 * 1440).ffill().bfill()
    else:
        df_copy['fng_change_3d'] = 0.0
        
    if 'funding_rate' in df_copy.columns:
        df_copy['funding_rate_mean_24h'] = df_copy['funding_rate'].rolling(window=24 * 60).mean().ffill().bfill()
    else:
        df_copy['funding_rate_mean_24h'] = 0.0
        
    if 'open_interest' in df_copy.columns:
        df_copy['open_interest_pct_change_4h'] = df_copy['open_interest'].pct_change(periods=4 * 60).ffill().bfill()
    else:
        df_copy['open_interest_pct_change_4h'] = 0.0

    # --- 4. CORRELAÇÕES DE MERCADO ---
    logger.debug("Calculando correlações de intermercado...")
    for asset in ['dxy', 'vix', 'spx', 'ndx', 'gold']:
        col_name = f"{asset}_close"
        corr_col_name = f"btc_{asset}_corr_30d"
        if col_name in df_copy.columns and 'close' in df_copy.columns:
            # Em modo live, calcular a correlação de 30 dias a cada minuto é muito lento.
            # Usamos um período menor para uma aproximação rápida.
            corr_window = '30D' if not live_mode else '1D' 
            df_copy[corr_col_name] = df_copy['close'].rolling(window=corr_window).corr(df_copy[col_name]).ffill().bfill()
        else:
            df_copy[corr_col_name] = 0.0

    # --- 5. CÁLCULO DO ALVO (TARGET) ---
    # Só executa se não estiver em modo live
    if not live_mode:
        logger.info("Calculando o alvo com o método da Barreira Tripla...")
        cfg = config_manager.get_section('DATA_PIPELINE')
        future_periods, profit_mult, stop_mult = int(cfg['future_periods']), float(cfg['profit_mult']), float(cfg['stop_mult'])

        if 'atr_14' not in df_copy.columns or df_copy['atr_14'].isnull().all():
            logger.error("A coluna 'atr_14' não pôde ser calculada. Impossível criar o target.")
            return df_copy

        atr = df_copy['atr_14'].ffill().bfill()
        take_profit_levels = df_copy['close'] + (atr * profit_mult)
        stop_loss_levels = df_copy['close'] - (atr * stop_mult)
        target = pd.Series(np.nan, index=df_copy.index)

        for i in tqdm(range(len(df_copy) - future_periods), desc="Calculando Target", file=sys.stderr):
            if pd.isna(take_profit_levels.iloc[i]) or pd.isna(stop_loss_levels.iloc[i]):
                continue

            future_highs = df_copy['high'].iloc[i+1 : i+1+future_periods]
            future_lows = df_copy['low'].iloc[i+1 : i+1+future_periods]
            
            hit_tp = future_highs[future_highs >= take_profit_levels.iloc[i]]
            hit_sl = future_lows[future_lows <= stop_loss_levels.iloc[i]]
            
            if not hit_tp.empty and not hit_sl.empty:
                target.iloc[i] = 1 if hit_tp.index[0] < hit_sl.index[0] else 0
            elif not hit_tp.empty:
                target.iloc[i] = 1
            elif not hit_sl.empty:
                target.iloc[i] = 0
                
        df_copy['target'] = target
        df_copy.dropna(subset=['target'], inplace=True)
        if not df_copy.empty:
            df_copy['target'] = df_copy['target'].astype(int)

    logger.debug("✅ Adição de features concluída.")

    # --- GARANTIA FINAL DE TIPOS ---
    # Garante que todas as colunas de feature sejam numéricas para evitar schema collision no InfluxDB
    feature_cols = df_copy.columns.drop(ohlc_cols + ['target'] if 'target' in df_copy.columns else ohlc_cols)
    for col in feature_cols:
        df_copy[col] = pd.to_numeric(df_copy[col], errors='coerce')

    # Preenche qualquer NaN que possa ter sido introduzido pela coerção
    df_copy.fillna(0.0, inplace=True)
    
    return df_copy
