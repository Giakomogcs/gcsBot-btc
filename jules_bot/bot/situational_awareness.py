import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
import ast

class SituationalAwareness:
    """
    Determina o regime de mercado atual usando uma abordagem baseada em regras,
    utilizando indicadores técnicos como ATR para volatilidade e MACD para tendência.
    Este modelo agora usa uma janela rolante para calcular os limiares, evitando o lookahead bias.
    """
    def __init__(self):
        # Mapeamento de regimes para melhor legibilidade e manutenção
        self.regime_map = {
            "RANGING": 0,
            "UPTREND": 1,
            "HIGH_VOLATILITY": 2,
            "DOWNTREND": 3
        }
        # Carrega a configuração da janela rolante do config.ini
        try:
            rolling_window_str = config_manager.get('DATA_PIPELINE', 'regime_rolling_window', fallback='72')
            self.rolling_window = int(rolling_window_str)
        except (ValueError, TypeError) as e:
            logger.warning(f"Não foi possível carregar 'regime_rolling_window' do config. Usando fallback para 72. Erro: {e}")
            self.rolling_window = 72 # Fallback

        self.volatility_percentile = 0.75 # O percentil do ATR a ser usado como limiar para alta volatilidade

    def transform(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica a lógica baseada em regras para determinar o regime de mercado para cada linha no DataFrame.
        Calcula um limiar de volatilidade dinâmico usando uma janela rolante para evitar lookahead bias.

        Args:
            features_df (pd.DataFrame): DataFrame com dados históricos, incluindo 'atr_14' e 'macd_diff_12_26_9'.

        Returns:
            pd.DataFrame: O DataFrame original com uma nova coluna 'market_regime'.
        """
        logger.info(f"Calculando regimes de mercado com uma janela rolante de {self.rolling_window} períodos...")
        
        df = features_df.copy()
        
        # Garante que as colunas necessárias existam
        required_cols = ['atr_14', 'macd_diff_12_26_9']
        if not all(col in df.columns for col in required_cols):
            logger.error(f"Faltando colunas cruciais para a detecção de regime: {required_cols}. Não é possível continuar.")
            raise ValueError(f"Missing required columns for regime detection: {required_cols}")

        # 1. Calcula o limiar de volatilidade rolante
        # O min_periods garante que temos dados suficientes para um cálculo significativo
        df['volatility_threshold'] = df['atr_14'].rolling(
            window=self.rolling_window,
            min_periods=self.rolling_window // 2
        ).quantile(self.volatility_percentile)

        # Preenche os NaNs. Primeiro, bfill para preencher os valores do início da série
        # e depois ffill para o restante. Isso garante que o cálculo de regime não falhe
        # nas primeiras linhas se elas contiverem NaNs.
        cols_to_fill = ['volatility_threshold', 'atr_14', 'macd_diff_12_26_9']
        df[cols_to_fill] = df[cols_to_fill].bfill().ffill()

        # Define uma função para aplicar a lógica de regime a cada linha de forma mais clara
        def get_regime(row):
            # A verificação de NaN é uma salvaguarda. Com bfill().ffill(), isso não deve ocorrer
            # a menos que toda a coluna seja NaN.
            if pd.isna(row['volatility_threshold']) or pd.isna(row['atr_14']) or pd.isna(row['macd_diff_12_26_9']):
                return -1  # Regime Indefinido

            is_high_volatility = row['atr_14'] > row['volatility_threshold']
            is_uptrend = row['macd_diff_12_26_9'] > 0
            is_downtrend = row['macd_diff_12_26_9'] < 0

            # A alta volatilidade tem a maior prioridade e sobrepõe outras condições.
            if is_high_volatility:
                return self.regime_map["HIGH_VOLATILITY"]

            # Em seguida, verificamos as tendências.
            if is_uptrend:
                return self.regime_map["UPTREND"]

            if is_downtrend:
                return self.regime_map["DOWNTREND"]

            # Se não houver volatilidade alta e o MACD estiver próximo de zero, consideramos "Ranging".
            # Este é o caso em que não é nem tendência de alta nem de baixa.
            return self.regime_map["RANGING"]

        # Aplica a função para determinar o regime. fillna(-1) para os casos (raros) em que todas as features são NaN.
        df['market_regime'] = df.apply(get_regime, axis=1).fillna(-1).astype(int)
        
        # Limpa a coluna de limiar que não é mais necessária fora deste contexto
        df.drop(columns=['volatility_threshold'], inplace=True)

        logger.info("Cálculo de regimes de mercado concluído.")
        return df