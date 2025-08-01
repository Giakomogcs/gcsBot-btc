# src/core/feature_engineering.py (VERSÃO MELHORADA COM LOGGING)

import pandas as pd
import numpy as np
import pandas_ta as ta
from tqdm import tqdm

from src.logger import logger
from src.config_manager import settings

def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Função central e única que adiciona todas as features de forma robusta,
    usando a lógica de 'col_names' para garantir a consistência.
    """
    logger.debug("Iniciando a adição de todas as features de engenharia...")
    df_copy = df.copy()

    # --- GARANTIA DE DADOS DE ENTRADA ---
    # Assegura que as colunas essenciais para os cálculos são numéricas
    ohlc_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in ohlc_cols:
        if col in df_copy.columns:
            df_copy[col] = pd.to_numeric(df_copy[col], errors='coerce')
    
    # Remove quaisquer linhas onde os dados OHLC fundamentais sejam nulos ANTES de calcular
    initial_rows = len(df_copy)
    df_copy.dropna(subset=ohlc_cols, inplace=True)
    if initial_rows > len(df_copy):
        logger.warning(f"Removidas {initial_rows - len(df_copy)} linhas com dados OHLC nulos antes da engenharia de features.")

    if df_copy.empty:
        logger.error("DataFrame ficou vazio após limpeza de OHLC. Abortando engenharia de features para este lote.")
        return pd.DataFrame()

    # --- 1. INDICADORES TÉCNICOS (usando a sua lógica 'col_names') ---
    logger.debug("Calculando indicadores técnicos com nomenclatura explícita...")
    df_copy.ta.rsi(length=14, append=True, col_names=('rsi_14',))
    df_copy.ta.macd(fast=12, slow=26, signal=9, append=True, col_names=('macd_12_26_9', 'macd_hist_12_26_9', 'macd_signal_12_26_9'))
    df_copy.ta.atr(length=14, append=True, col_names=('atr_14',))
    df_copy.ta.bbands(length=20, std=2, append=True, col_names=('bbl_20_2_0', 'bbm_20_2_0', 'bbu_20_2_0', 'bbb_20_2_0', 'bbp_20_2_0'))

    # Renomeia o 'macd_hist' para 'macd_diff' para consistência com o plano
    if 'macd_hist_12_26_9' in df_copy.columns:
        df_copy.rename(columns={'macd_hist_12_26_9': 'macd_diff_12_26_9'}, inplace=True)

    # --- 2. FEATURES DE FLUXO DE ORDENS ---
    logger.debug("Calculando features de fluxo de ordens...")
    if 'taker_buy_volume' not in df_copy.columns: df_copy['taker_buy_volume'] = 0.0
    if 'taker_sell_volume' not in df_copy.columns: df_copy['taker_sell_volume'] = 0.0
    df_copy['volume_delta'] = df_copy['taker_buy_volume'] - df_copy['taker_sell_volume']
    df_copy['cvd'] = df_copy['volume_delta'].cumsum()

    # --- 3. CORRELAÇÕES DE MERCADO ---
    logger.debug("Calculando correlações de intermercado...")
    # Garante que as colunas de correlação existem antes de tentar usá-las
    if 'dxy_close' in df_copy.columns and 'close' in df_copy.columns:
        corr_window = '30D'
        df_copy['btc_dxy_corr_30d'] = df_copy['close'].rolling(window=corr_window).corr(df_copy['dxy_close']).ffill().bfill()
        df_copy['btc_vix_corr_30d'] = df_copy['close'].rolling(window=corr_window).corr(df_copy['vix_close']).ffill().bfill()
    else:
        logger.warning("Colunas 'dxy_close' ou 'vix_close' não encontradas. Features de correlação não serão criadas.")
        df_copy['btc_dxy_corr_30d'] = 0.0
        df_copy['btc_vix_corr_30d'] = 0.0


    # --- 4. CÁLCULO DO ALVO (TARGET) ---
    logger.info("Calculando o alvo com o método da Barreira Tripla...")
    cfg = settings.data_pipeline.target
    future_periods, profit_mult, stop_mult = cfg.future_periods, cfg.profit_mult, cfg.stop_mult

    # Esta verificação agora vai funcionar, pois garantimos que a entrada é válida.
    if 'atr_14' not in df_copy.columns or df_copy['atr_14'].isnull().all():
        logger.error("A coluna 'atr_14' não pôde ser calculada. Impossível criar o target. Abortando para este lote.")
        return df_copy # Retorna o dataframe sem o target para análise do erro

    atr = df_copy['atr_14'].ffill().bfill() # Preenchemos possíveis NaNs no ATR para robustez
    take_profit_levels = df_copy['close'] + (atr * profit_mult)
    stop_loss_levels = df_copy['close'] - (atr * stop_mult)
    target = pd.Series(np.nan, index=df_copy.index)

    for i in tqdm(range(len(df_copy) - future_periods), desc="Calculando Target"):
        # Garante que os níveis de TP/SL são válidos antes de usar
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
    
    # --- LOG DE DIAGNÓSTICO CRÍTICO ---
    total_rows_before_drop = len(df_copy)
    nan_targets = df_copy['target'].isnull().sum()
    logger.info(f"Diagnóstico do Target: {total_rows_before_drop} linhas totais. {nan_targets} targets não puderam ser calculados (normal para o final do período).")

    df_copy.dropna(subset=['target'], inplace=True)
    logger.info(f"Após remoção de targets nulos, restaram {len(df_copy)} linhas.")

    if not df_copy.empty:
        df_copy['target'] = df_copy['target'].astype(int)

    logger.debug("✅ Adição de features e target concluída.")
    return df_copy