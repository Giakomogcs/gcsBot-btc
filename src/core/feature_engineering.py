# src/core/feature_engineering.py
import pandas as pd
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator, CCIIndicator
from ta.momentum import StochasticOscillator, RSIIndicator, WilliamsRIndicator
from src.logger import logger

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona um conjunto de indicadores técnicos ao DataFrame."""
    logger.info("Calculando indicadores técnicos...")
    
    # Garante que o DataFrame está ordenado por tempo
    df = df.sort_index()
    
    # Indicadores que já tínhamos
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
    
    # <<< --- ADICIONANDO AS FEATURES QUE FALTAVAM --- >>>
    df['price_change_1m'] = df['close'].pct_change(1)
    df['price_change_5m'] = df['close'].pct_change(5)
    df['momentum_10m'] = df['close'].pct_change(10)
    
    atr_short = df['atr'].rolling(window=5).mean()
    atr_long = df['atr'].rolling(window=100).mean()
    # Adicionamos um epsilon para evitar divisão por zero
    df['volatility_ratio'] = atr_short / (atr_long + 1e-10) 
    
    df['cci'] = CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()
    df['williams_r'] = WilliamsRIndicator(high=df['high'], low=df['low'], close=df['close'], lbp=14).williams_r()
    
    return df

def add_order_flow_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona features baseadas em fluxo de ordens (Order Flow)."""
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
    
    # <<< --- CORRIGINDO O FUTUREWARNING --- >>>
    # Preenche quaisquer valores nulos iniciais que os indicadores possam criar
    df_with_features = df_with_features.bfill()
    
    logger.info("✅ Engenharia de features concluída.")
    return df_with_features