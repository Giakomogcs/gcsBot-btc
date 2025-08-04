# src/core/anomaly_detector.py

import pandas as pd
from sklearn.ensemble import IsolationForest
from gcs_bot.utils.logger import logger

class AnomalyDetector:
    def __init__(self, contamination=0.01, random_state=42):
        self.contamination = contamination
        self.random_state = random_state
        self.model = IsolationForest(contamination=self.contamination, random_state=self.random_state)

    def train(self, df: pd.DataFrame, features: list):
        logger.info("Training anomaly detection model...")
        df_train = df[features].copy()
        df_train.dropna(inplace=True)
        self.model.fit(df_train)
        logger.info("Anomaly detection model trained.")

    def predict(self, df: pd.DataFrame, features: list) -> pd.Series:
        logger.info("Predicting anomalies...")
        df_predict = df[features].copy()
        df_predict.dropna(inplace=True)
        return self.model.predict(df_predict)
