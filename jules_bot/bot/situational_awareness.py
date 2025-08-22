import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
import ast

class SituationalAwareness:
    """
    Determina o regime de mercado atual usando uma abordagem baseada em regras,
    utilizando indicadores técnicos como ATR para volatilidade e MACD para tendência.
    """
    def __init__(self):
        # O limiar de volatilidade (baseado no ATR) será determinado pelo método fit()
        self.volatility_threshold = None
        self.is_fitted = False
        # Mapeamento de regimes para melhor legibilidade e manutenção
        self.regime_map = {
            "RANGING": 0,
            "UPTREND": 1,
            "HIGH_VOLATILITY": 2,
            "DOWNTREND": 3
        }

    def fit(self, features_df: pd.DataFrame, volatility_percentile: float = 0.75):
        """
        Calcula o limiar de volatilidade a partir de dados históricos.
        Este método "treina" o classificador de regime.

        Args:
            features_df (pd.DataFrame): DataFrame contendo dados históricos com a coluna 'atr_14'.
            volatility_percentile (float): O percentil do ATR a ser usado como limiar para alta volatilidade.
        """
        logger.info("Calculando limiares para o modelo de regime baseado em regras...")
        
        # Garante que a coluna 'atr_14' exista e não tenha NaNs para o cálculo
        if 'atr_14' not in features_df.columns or features_df['atr_14'].isnull().all():
            logger.error("A coluna 'atr_14' não está disponível ou está vazia. Não é possível treinar o modelo de regime.")
            return

        # Calcula o limiar de volatilidade com base no percentil definido
        self.volatility_threshold = features_df['atr_14'].quantile(volatility_percentile)
        self.is_fitted = True

        logger.info(f"✅ Modelo de regime treinado. Limiar de volatilidade (ATR > {volatility_percentile:.0%}): {self.volatility_threshold:.4f}")

    def transform(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica a lógica baseada em regras para determinar o regime de mercado para cada linha no DataFrame.

        Args:
            features_df (pd.DataFrame): DataFrame com os dados de vela mais recentes, incluindo 'atr_14' e 'macd_diff_12_26_9'.

        Returns:
            pd.DataFrame: O DataFrame original com uma nova coluna 'market_regime'.
        """
        if not self.is_fitted:
            raise RuntimeError("O modelo de SituationalAwareness deve ser treinado (.fit()) antes de ser usado (.transform()).")
        
        df = features_df.copy()
        
        # Extrai as features de regime do config, embora agora usemos lógica explícita
        regime_features = ast.literal_eval(config_manager.get('DATA_PIPELINE', 'regime_features'))

        # Garante que as colunas necessárias existam
        required_cols = ['atr_14', 'macd_diff_12_26_9']
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"Faltando colunas necessárias para a detecção de regime: {required_cols}. Retornando regime de fallback (-1).")
            df['market_regime'] = -1
            return df

        # Define uma função para aplicar a lógica de regime a cada linha
        def get_regime(row):
            # 1. Checa por alta volatilidade primeiro, pois é o regime prioritário
            if row['atr_14'] > self.volatility_threshold:
                return self.regime_map["HIGH_VOLATILITY"]

            # 2. Checa por tendência de alta
            if row['macd_diff_12_26_9'] > 0:
                return self.regime_map["UPTREND"]

            # 3. Checa por tendência de baixa
            if row['macd_diff_12_26_9'] < 0:
                return self.regime_map["DOWNTREND"]

            # 4. Se nenhuma das condições acima for atendida, é um mercado em range
            return self.regime_map["RANGING"]

        # Aplica a função para determinar o regime. fillna(-1) para casos onde as features são NaN
        df['market_regime'] = df.apply(get_regime, axis=1).fillna(-1).astype(int)
        
        return df