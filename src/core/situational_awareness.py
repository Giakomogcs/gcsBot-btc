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
        
        # Ensure all required features are present
        missing_features = [f for f in features_for_clustering if f not in df.columns]
        if missing_features:
            raise ValueError(f"Missing features for clustering: {missing_features}")

        # Create a copy to avoid SettingWithCopyWarning
        df_copy = df.copy()

        # Drop rows with NaN values in the features to be scaled
        df_copy.dropna(subset=features_for_clustering, inplace=True)

        if df_copy.empty:
            logger.warning("DataFrame is empty after dropping NaNs. Cannot perform clustering.")
            # Return the original dataframe with an empty 'market_situation' column
            df['market_situation'] = pd.Series(dtype='int')
            return df

        scaled_features = self.scaler.fit_transform(df_copy[features_for_clustering])
        
        # Get the predictions
        predictions = self.kmeans.fit_predict(scaled_features)
        
        # Create a new DataFrame for the predictions
        df_predictions = pd.DataFrame(predictions, index=df_copy.index, columns=['market_situation'])
        
        # Join the predictions back to the original DataFrame
        df = df.join(df_predictions, how='left')

        logger.info("Clustering complete.")
        return df
