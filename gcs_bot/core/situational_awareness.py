import pandas as pd
import joblib
import os
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings

class SituationalAwareness:
    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self.cluster_model = KMeans(n_clusters=self.n_regimes, random_state=42, n_init='auto')
        self.scaler = StandardScaler()
        self.is_fitted = False

    def fit(self, features_df: pd.DataFrame):
        logger.info(f"Treinando o modelo de {self.n_regimes} regimes de mercado...")
        regime_features = settings.data_pipeline.regime_features
        
        df = features_df.dropna(subset=regime_features).copy()
        if df.empty:
            logger.error("Não há dados suficientes para treinar o modelo de regimes.")
            return

        scaled_features = self.scaler.fit_transform(df[regime_features])
        self.cluster_model.fit(scaled_features)
        self.is_fitted = True
        logger.info("✅ Modelo de regimes de mercado treinado com sucesso.")

    def transform(self, features_df: pd.DataFrame) -> pd.DataFrame:
        if not self.is_fitted:
            raise RuntimeError("O modelo de SituationalAwareness deve ser treinado (.fit()) antes de ser usado (.transform()).")
        
        logger.debug("Aplicando rótulos de regime de mercado...")
        regime_features = settings.data_pipeline.regime_features
        df = features_df.copy()
        
        # Garante que as colunas existam
        valid_rows = df.dropna(subset=regime_features)
        if valid_rows.empty:
            df['market_regime'] = -1
            return df

        scaled_features = self.scaler.transform(valid_rows[regime_features])
        regime_labels = self.cluster_model.predict(scaled_features)
        
        df['market_regime'] = -1
        df.loc[valid_rows.index, 'market_regime'] = regime_labels
        
        return df

    def save_model(self, path: str):
        """Salva o modelo treinado e o scaler."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({'cluster_model': self.cluster_model, 'scaler': self.scaler}, path)
        logger.info(f"Modelo de SituationalAwareness salvo em: {path}")

    @classmethod
    def load_model(cls, path: str):
        """Carrega um modelo e scaler pré-treinados."""
        if not os.path.exists(path):
            logger.error(f"Arquivo do modelo de SituationalAwareness não encontrado em {path}")
            return None
            
        artefacts = joblib.load(path)
        n_clusters = artefacts['cluster_model'].n_clusters
        
        instance = cls(n_regimes=n_clusters)
        instance.cluster_model = artefacts['cluster_model']
        instance.scaler = artefacts['scaler']
        instance.is_fitted = True
        
        logger.info(f"Modelo de SituationalAwareness carregado de: {path}")
        return instance