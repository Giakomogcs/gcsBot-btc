# src/model_trainer.py (VERSÃO 6.0 - LIMPO E ALINHADO)

import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler
from numba import jit
from typing import Tuple, List, Any

from src.logger import logger, log_table
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator, CCIIndicator
from ta.momentum import StochasticOscillator, RSIIndicator, WilliamsRIndicator

@jit(nopython=True)
def create_labels_triple_barrier(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, atr: np.ndarray,
    future_periods: int, profit_multiplier: float, stop_multiplier: float
) -> np.ndarray:
    """
    Implementação da Barreira Tripla com 3 classes de rótulos:
    - 1: Compra (barreira de lucro atingida)
    - 2: Venda (barreira de stop atingida)
    - 0: Neutro (tempo esgotado sem tocar nas barreiras)
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int64)
    for i in range(n - future_periods):
        if atr[i] <= 1e-10: continue
        
        profit_barrier = closes[i] + (atr[i] * profit_multiplier)
        stop_barrier = closes[i] - (atr[i] * stop_multiplier)
        
        for j in range(1, future_periods + 1):
            future_high, future_low = highs[i + j], lows[i + j]
            
            if future_high >= profit_barrier:
                labels[i] = 1 # Lucro
                break
            if future_low <= stop_barrier:
                labels[i] = 2 # Prejuízo
                break
                
    return labels

class ModelTrainer:
    def __init__(self):
        self.base_feature_names = [
            'rsi', 'rsi_1h', 'rsi_4h', 'macd_diff', 'macd_diff_1h', 'stoch_osc',
            'adx', 'adx_power',
            'atr', 'bb_width', 'bb_pband',
            'sma_7_25_diff', 'close_sma_25_dist',
            'price_change_1m', 'price_change_5m',
            'dxy_close_change', 'vix_close_change',
            'gold_close_change', 'tnx_close_change',
            'atr_long_avg', 
            'volume_sma_50',
            'cci',
            'williams_r',
            'momentum_10m',
            'volatility_ratio',
            'sma_50_200_diff'
        ]

    def _prepare_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        logger.debug("Iniciando preparação de features...")
        epsilon = 1e-10
        
        # --- Cálculo de Indicadores Técnicos ---
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / (bb.bollinger_mavg() + epsilon)
        df['bb_pband'] = bb.bollinger_pband()

        sma_7 = df['close'].rolling(window=7).mean()
        sma_25 = df['close'].rolling(window=25).mean()
        sma_50 = df['close'].rolling(window=50).mean()
        sma_200 = df['close'].rolling(window=200).mean()
        df['sma_7_25_diff'] = (sma_7 - sma_25) / (df['close'] + epsilon)
        df['close_sma_25_dist'] = (df['close'] - sma_25) / (sma_25 + epsilon)
        
        df['macd_diff'] = MACD(close=df['close']).macd_diff()
        
        adx_indicator = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
        df['adx'] = adx_indicator.adx()
        df['adx_power'] = (adx_indicator.adx_pos() - adx_indicator.adx_neg())

        df['price_change_1m'] = df['close'].pct_change(1)
        df['price_change_5m'] = df['close'].pct_change(5)
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        df['stoch_osc'] = StochasticOscillator(high=df['high'], low=df['low'], close=df['close']).stoch()
        
        df['atr_long_avg'] = df['atr'].rolling(window=100).mean()
        df['volume_sma_50'] = df['volume'].rolling(window=50).mean()

        df['cci'] = CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()
        df['williams_r'] = WilliamsRIndicator(high=df['high'], low=df['low'], close=df['close'], lbp=14).williams_r()
        df['momentum_10m'] = df['close'].pct_change(10)
        atr_short = df['atr'].rolling(window=5).mean()
        df['volatility_ratio'] = atr_short / (df['atr_long_avg'] + epsilon)
        df['sma_50_200_diff'] = (sma_50 - sma_200) / (df['close'] + epsilon)

        macro_map = {
            'dxy_close': 'dxy_close_change', 'vix_close': 'vix_close_change',
            'gold_close': 'gold_close_change', 'tnx_close': 'tnx_close_change'
        }
        for col_in, col_out in macro_map.items():
            df[col_out] = df[col_in].pct_change(60).fillna(0) if col_in in df.columns else 0

        df_1h = df['close'].resample('h').last()
        df['rsi_1h'] = RSIIndicator(close=df_1h, window=14).rsi().reindex(df.index, method='ffill')
        df['macd_diff_1h'] = MACD(close=df_1h).macd_diff().reindex(df.index, method='ffill')
        df_4h = df['close'].resample('4h').last()
        df['rsi_4h'] = RSIIndicator(close=df_4h, window=14).rsi().reindex(df.index, method='ffill')
        for col in ['rsi_1h', 'macd_diff_1h', 'rsi_4h']:
            df[col] = df[col].bfill().ffill()

        # --- Construção da lista final de features ---
        final_feature_names = sorted(list(set(self.base_feature_names.copy())))
        
        # <<< REMOÇÃO DA LÓGICA DE ONE-HOT ENCODING >>>
        # Um especialista de regime já opera sob a condição daquele regime.
        # Adicionar o regime como feature é redundante e pode confundir o modelo.
        
        for col in final_feature_names:
            if col not in df.columns:
                df[col] = 0.0

        df_final = df.copy()
        df_final[final_feature_names] = df_final[final_feature_names].shift(1)
        df_final.replace([np.inf, -np.inf], np.nan, inplace=True)
        df_final.dropna(subset=final_feature_names, inplace=True)
        
        return df_final, final_feature_names

    def train(self, data: pd.DataFrame, all_params: dict) -> Tuple[LGBMClassifier | None, StandardScaler | None, List[str] | None]:
        """
        Prepara os dados, treina o modelo e retorna o modelo, o normalizador
        e a lista de features utilizadas.
        """
        if len(data) < 500:
            logger.warning(f"Dados insuficientes para treino ({len(data)} registros). Pulando.")
            return None, None, None

        logger.debug("Iniciando o processo de treino do modelo...")
        df_processed, final_feature_names = self._prepare_features(data.copy())

        if df_processed.empty:
            logger.warning("DataFrame ficou vazio após a preparação de features. Pulando trial.")
            return None, None, None

        future_periods = all_params.get('future_periods', 30)
        profit_mult = all_params.get('profit_mult', 2.0)
        stop_mult = all_params.get('stop_mult', 2.0)

        labels_np = create_labels_triple_barrier(
            closes=df_processed['close'].to_numpy(), highs=df_processed['high'].to_numpy(),
            lows=df_processed['low'].to_numpy(), atr=df_processed['atr'].to_numpy(),
            future_periods=future_periods, profit_multiplier=profit_mult, stop_multiplier=stop_mult
        )
        y = pd.Series(labels_np, index=df_processed.index, name="label")
        
        X = df_processed[final_feature_names]

        counts = y.value_counts()
        if counts.get(1, 0) < 15 or counts.get(2, 0) < 15:
            logger.warning(f"Não há exemplos suficientes de compra(1) ou venda(2). Counts: {counts.to_dict()}")
            return None, None, None

        logger.info(f"Treinando modelo com {len(final_feature_names)} features.")
        log_table("Distribuição dos Labels no Treino", y.value_counts(normalize=True).reset_index(), headers=["Label", "Frequência"])
        
        scaler = StandardScaler()
        X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)
        
        model_params = {k: v for k, v in all_params.items() if k in LGBMClassifier().get_params().keys()}
        
        model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
        model.fit(X_scaled, y)

        logger.debug("Treinamento do modelo concluído com sucesso.")
        
        return model, scaler, final_feature_names