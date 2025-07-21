# src/situational_awareness.py

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from src.logger import logger

class SituationalAwareness:
    def __init__(self, n_clusters=10, random_state=42):
        self.n_clusters = n_clusters
        self.random_state = random_state
        self.kmeans = KMeans(n_clusters=self.n_clusters, random_state=self.random_state, n_init=10)
        self.scaler = StandardScaler()

    def cluster_data(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info(f"Clustering data into {self.n_clusters} market situations...")

        features_for_clustering = [
            'rsi', 'macd_diff', 'atr', 'bb_width', 'volume_sma_50'
        ]

        df_cluster = df[features_for_clustering].copy()
        df_cluster.dropna(inplace=True)

        scaled_features = self.scaler.fit_transform(df_cluster)

        df['market_situation'] = self.kmeans.fit_predict(scaled_features)

        logger.info("Clustering complete.")
        return df
