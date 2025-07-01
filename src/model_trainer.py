# src/model_trainer.py

import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler
import joblib
from numba import jit

from src.logger import logger
from src.config import MODEL_FILE, SCALER_FILE
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator
from ta.momentum import StochasticOscillator

@jit(nopython=True)
def create_labels_triple_barrier(
    closes: np.ndarray, 
    highs: np.ndarray, 
    lows: np.ndarray, 
    atr: np.ndarray, 
    future_periods: int, 
    profit_multiplier: float, 
    stop_multiplier: float
) -> np.ndarray:
    """
    Implementação profissional do Método da Barreira Tripla (Triple-Barrier Method).
    Cria labels (1 para Compra/Lucro, 2 para Venda/Prejuízo) com base em alvos dinâmicos.
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int64)

    for i in range(n - future_periods):
        if atr[i] == 0: continue

        profit_barrier = closes[i] + (atr[i] * profit_multiplier)
        stop_barrier = closes[i] - (atr[i] * stop_multiplier)
        
        target_hit = False
        for j in range(1, future_periods + 1):
            future_high, future_low = highs[i + j], lows[i + j]
            if future_high >= profit_barrier:
                labels[i] = 1
                target_hit = True
                break
            if future_low <= stop_barrier:
                labels[i] = 2
                target_hit = True
                break
        
        if not target_hit:
            labels[i] = 1 if closes[i + future_periods] > closes[i] else 2

    return labels

class ModelTrainer:
    """
    Classe responsável por preparar os dados, treinar o modelo de Machine Learning
    e salvá-lo para uso posterior pelo bot de trading.
    """
    def __init__(self):
        # Lista definitiva de features. A "mente" completa do bot.
        self.feature_names = [
            'sma_7', 'sma_25', 'rsi', 'price_change_1m', 'price_change_5m',
            'bb_width', 'bb_pband', # Adicionada a feature %B (pband)
            'atr', 'macd_diff', 'stoch_osc',
            'adx', 'adx_pos', 'adx_neg', # Features de Regime de Mercado
            'dxy_close_change', 'vix_close_change', # Features Macro
            'gold_close_change', 'tnx_close_change'
        ]

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula todos os indicadores técnicos e macroeconômicos (features) para o modelo,
        com lógica robusta para evitar NaNs e elimina o look-ahead bias.
        """
        epsilon = 1e-10
        
        # --- Volatilidade e Bandas de Bollinger ---
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / (bb.bollinger_mavg() + epsilon)
        df['bb_pband'] = bb.bollinger_pband() # %B para identificar sobrecompra/venda em mercados laterais

        # --- Tendência e Regime de Mercado ---
        df['sma_7'] = df['close'].rolling(window=7).mean()
        df['sma_25'] = df['close'].rolling(window=25).mean()
        df['macd_diff'] = MACD(close=df['close']).macd_diff()
        adx_indicator = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
        df['adx'], df['adx_pos'], df['adx_neg'] = adx_indicator.adx(), adx_indicator.adx_pos(), adx_indicator.adx_neg()

        # --- Momento ---
        df['price_change_1m'] = df['close'].pct_change(1)
        df['price_change_5m'] = df['close'].pct_change(5)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / (loss + epsilon))))
        df['stoch_osc'] = StochasticOscillator(high=df['high'], low=df['low'], close=df['close']).stoch()

        # --- Features Macroeconômicas (Variação na última hora) ---
        macro_map = {
            'dx_close': 'dxy_close_change',
            'vix_close': 'vix_close_change',
            'gc_close': 'gold_close_change',
            'tnx_close': 'tnx_close_change'
        }
        for col_in, col_out in macro_map.items():
            if col_in in df.columns:
                df[col_out] = df[col_in].pct_change(60).fillna(0)
            else:
                df[col_out] = 0 # Garante que a coluna exista mesmo que a busca de dados falhe
        
        # --- CORREÇÃO CRÍTICA: ELIMINAÇÃO DO LOOK-AHEAD BIAS ---
        # Desloca todas as colunas de features em uma vela para o futuro.
        df[self.feature_names] = df[self.feature_names].shift(1)
        
        # Limpeza final de dados
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)
        
        return df

    def train(self, data: pd.DataFrame, all_params: dict):
        if len(data) < 500:
            logger.warning(f"Dados insuficientes para treino ({len(data)} registros). Pulando.")
            return None, None

        logger.debug("Iniciando preparação de features para o treinamento...")
        df_full = self._prepare_features(data.copy())
        
        if df_full.empty:
            logger.warning("DataFrame ficou vazio após a preparação de features. Pulando trial.")
            return None, None

        future_periods = all_params.get('future_periods', 30)
        profit_mult = all_params.get('profit_mult', 2.0)
        stop_mult = all_params.get('stop_mult', 2.0)
        
        logger.debug(f"Gerando labels com: future_periods={future_periods}, profit_mult={profit_mult}, stop_mult={stop_mult}")
        
        labels_np = create_labels_triple_barrier(
            closes=df_full['close'].to_numpy(), highs=df_full['high'].to_numpy(),
            lows=df_full['low'].to_numpy(), atr=df_full['atr'].to_numpy(),
            future_periods=future_periods, profit_multiplier=profit_mult, stop_multiplier=stop_mult
        )
        
        y = pd.Series(labels_np, index=df_full.index, name="label")
        X = df_full[self.feature_names]
        
        if y.value_counts().get(1, 0) < 20 or y.value_counts().get(2, 0) < 20:
            logger.warning(f"Não há exemplos suficientes de compra/venda. Counts: {y.value_counts().to_dict()}")
            return None, None
            
        logger.debug("Normalizando features e treinando o modelo LightGBM...")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        model_params = {
            'n_estimators': all_params.get('n_estimators', 200),
            'learning_rate': all_params.get('learning_rate', 0.05),
            'num_leaves': all_params.get('num_leaves', 31),
            'max_depth': all_params.get('max_depth', 10),
            'min_child_samples': all_params.get('min_child_samples', 20),
            'feature_fraction': all_params.get('feature_fraction', 0.8),
            'bagging_fraction': all_params.get('bagging_fraction', 0.8),
            'bagging_freq': all_params.get('bagging_freq', 1),
            'lambda_l1': all_params.get('lambda_l1', 0.1),
            'lambda_l2': all_params.get('lambda_l2', 0.1),
        }

        model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
        model.fit(X_scaled, y)
        
        logger.debug("Treinamento do modelo concluído com sucesso.")
        return model, scaler

    def save_model(self, model, scaler):
        """Salva o modelo e o normalizador de features em arquivos .pkl."""
        joblib.dump(model, MODEL_FILE)
        joblib.dump(scaler, SCALER_FILE)
        logger.info(f"✅ Modelo final e robusto salvo em '{MODEL_FILE}' e '{SCALER_FILE}'")