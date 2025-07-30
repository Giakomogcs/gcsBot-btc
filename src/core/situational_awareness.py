import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from src.logger import logger

class SituationalAwareness:
    """
    Analisa a tabela de features para identificar e rotular diferentes
    regimes de mercado usando clustering.
    """
    def __init__(self, n_regimes: int = 4):
        """
        Inicializa o módulo.
        
        Args:
            n_regimes (int): O número de diferentes "situações" de mercado
                             que queremos que o modelo identifique.
        """
        self.n_regimes = n_regimes
        # Usaremos KMeans para agrupar as características do mercado em regimes
        self.cluster_model = KMeans(n_clusters=self.n_regimes, random_state=42, n_init=10)
        self.scaler = StandardScaler()

    def determine_regimes(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """
        Adiciona a coluna 'market_regime' ao DataFrame.

        Args:
            features_df (pd.DataFrame): O DataFrame completo da features_master_table.

        Returns:
            pd.DataFrame: O mesmo DataFrame com a coluna 'market_regime' adicionada.
        """
        logger.info(f"Iniciando a determinação de {self.n_regimes} regimes de mercado...")

        # Selecionamos as características que definem um "regime".
        # Volatilidade (atr) e tendência (usando a diferença entre médias) são bons começos.
        # Sinta-se à vontade para adicionar outras, como 'volume_delta' ou 'momentum_10m'.
        regime_features = ['atr', 'macd_diff', 'rsi'] # Exemplo inicial
        
        df = features_df.copy()

        # Garante que as features existem
        for feature in regime_features:
            if feature not in df.columns:
                logger.error(f"Feature '{feature}' para determinação de regime não encontrada no DataFrame. Abortando.")
                # Retorna o DF original sem a coluna de regime
                return features_df

        # Removemos valores nulos que podem ter sido gerados no cálculo das features
        df.dropna(subset=regime_features, inplace=True)
        if df.empty:
            logger.error("Após remover NaNs, não restaram dados para determinar regimes. Verifique o data_pipeline.")
            return features_df

        # Normalizamos os dados para que o KMeans funcione corretamente
        scaled_features = self.scaler.fit_transform(df[regime_features])

        # Treina o modelo de clustering e atribui um regime a cada linha
        regime_labels = self.cluster_model.fit_predict(scaled_features)

        # Adiciona os rótulos de regime de volta ao DataFrame
        df['market_regime'] = regime_labels
        
        logger.info("Análise de regimes de mercado concluída.")
        # Exibe um resumo de quantos pontos de dados caíram em cada regime
        logger.info(f"Distribuição dos regimes:\n{df['market_regime'].value_counts().sort_index()}")

        # Retorna o DataFrame original com a nova coluna, preenchendo com -1 onde não foi possível calcular
        return features_df.join(df[['market_regime']]).fillna({'market_regime': -1})