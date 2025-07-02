# src/model_trainer.py (VERSÃO FINAL COM REGIMES E 3 CLASSES DE LABEL)

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
from ta.momentum import StochasticOscillator, RSIIndicator

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
    Implementação da Barreira Tripla com 3 classes de rótulos:
    - 1: Compra (barreira de lucro atingida)
    - 2: Venda (barreira de stop atingida)
    - 0: Neutro (tempo esgotado sem tocar nas barreiras)
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int64) # O padrão agora é 0 (Neutro)
    for i in range(n - future_periods):
        if atr[i] <= 1e-10: continue
        
        profit_barrier = closes[i] + (atr[i] * profit_multiplier)
        stop_barrier = closes[i] - (atr[i] * stop_multiplier)
        
        for j in range(1, future_periods + 1):
            future_high, future_low = highs[i + j], lows[i + j]
            
            if future_high >= profit_barrier:
                labels[i] = 1 # Lucro
                break # Sai do loop interno, pois o resultado foi definido
            
            if future_low <= stop_barrier:
                labels[i] = 2 # Prejuízo
                break # Sai do loop interno, pois o resultado foi definido
                
        # Se o loop terminar sem atingir lucro ou prejuízo, o label permanece 0 (Neutro).
        # A lógica antiga que forçava uma decisão foi removida.
        
    return labels

class ModelTrainer:
    def __init__(self):
        # A lista de features com os regimes está perfeita, mantemos ela.
        self.feature_names = [
            'sma_7', 'sma_25', 'rsi', 'price_change_1m', 'price_change_5m',
            'bb_width', 'bb_pband',
            'atr', 'macd_diff', 'stoch_osc',
            'adx', 'adx_pos', 'adx_neg',
            'regime_tendencia', 'regime_volatilidade',
            'dxy_close_change', 'vix_close_change',
            'gold_close_change', 'tnx_close_change',
            'rsi_1h', 'macd_diff_1h', 'rsi_4h'
        ]

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        # Sua função _prepare_features está excelente e não precisa de alterações.
        logger.debug("Preparando features com a estratégia híbrida...")
        epsilon = 1e-10
        
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / (bb.bollinger_mavg() + epsilon)
        df['bb_pband'] = bb.bollinger_pband()

        df['sma_7'] = df['close'].rolling(window=7).mean()
        df['sma_25'] = df['close'].rolling(window=25).mean()
        df['macd_diff'] = MACD(close=df['close']).macd_diff()
        
        adx_indicator = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
        df['adx'], df['adx_pos'], df['adx_neg'] = adx_indicator.adx(), adx_indicator.adx_pos(), adx_indicator.adx_neg()
        df['sma_200'] = df['close'].rolling(window=200).mean()
        df['regime_tendencia'] = (df['close'] > df['sma_200']).astype(int)
        df['atr_mean_50'] = df['atr'].rolling(window=50).mean()
        df['regime_volatilidade'] = (df['atr'] > df['atr_mean_50']).astype(int)

        df['price_change_1m'] = df['close'].pct_change(1)
        df['price_change_5m'] = df['close'].pct_change(5)
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        df['stoch_osc'] = StochasticOscillator(high=df['high'], low=df['low'], close=df['close']).stoch()

        macro_map = {
            'dxy_close': 'dxy_close_change', 'vix_close': 'vix_close_change',
            'gold_close': 'gold_close_change', 'tnx_close': 'tnx_close_change'
        }
        for col_in, col_out in macro_map.items():
            if col_in in df.columns:
                df[col_out] = df[col_in].pct_change(60).fillna(0)
            else:
                df[col_out] = 0

        logger.debug("Adicionando features de contexto de 1h e 4h...")
        
        # Agrega os dados para 1 hora
        df_1h = df['close'].resample('h').last()
        df['rsi_1h'] = RSIIndicator(close=df_1h, window=14).rsi().reindex(df.index, method='ffill')
        df['macd_diff_1h'] = MACD(close=df_1h, window_fast=12, window_slow=26, window_sign=9).macd_diff().reindex(df.index, method='ffill')

        # Agrega os dados para 4 horas
        df_4h = df['close'].resample('4h').last()
        df['rsi_4h'] = RSIIndicator(close=df_4h, window=14).rsi().reindex(df.index, method='ffill')
        
        # Preenche quaisquer NaNs restantes no início do dataframe
        for col in ['rsi_1h', 'macd_diff_1h', 'rsi_4h']:
            df[col] = df[col].bfill()
        
        df[self.feature_names] = df[self.feature_names].shift(1)
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)
        return df

    def train(self, data: pd.DataFrame, all_params: dict):
        """Prepara os dados, treina e retorna o modelo e o normalizador."""
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

        logger.info(f"Distribuição dos labels no treino: \n{y.value_counts(normalize=True)}")
        
        # Agora, a verificação precisa garantir que temos exemplos de todas as classes, especialmente 1 e 2.
        counts = y.value_counts()
        if counts.get(1, 0) < 20 or counts.get(2, 0) < 20:
            logger.warning(f"Não há exemplos suficientes de compra(1)/venda(2) para um treino confiável. Counts: {counts.to_dict()}")
            return None, None

        logger.debug("Normalizando features e treinando o modelo LightGBM...")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model_params = all_params # Passa todos os parâmetros otimizáveis para o modelo
        
        # O LightGBM lida nativamente com classificação multiclasse. Nenhuma mudança necessária aqui.
        model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
        model.fit(X_scaled, y)

        logger.debug("Treinamento do modelo concluído com sucesso.")
        return model, scaler

    def save_model(self, model, scaler):
        joblib.dump(model, MODEL_FILE); joblib.dump(scaler, SCALER_FILE)
        logger.info(f"✅ Modelo e normalizador salvos em '{MODEL_FILE}' e '{SCALER_FILE}'")