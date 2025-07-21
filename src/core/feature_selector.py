# src/core/feature_selector.py

import pandas as pd
from sklearn.feature_selection import SelectKBest, f_classif
from src.logger import logger

class FeatureSelector:
    def __init__(self, k=10):
        self.k = k
        self.selector = SelectKBest(f_classif, k=self.k)

    def select_features(self, X: pd.DataFrame, y: pd.Series) -> list:
        logger.info(f"Selecting {self.k} best features...")
        self.selector.fit(X, y)
        selected_features = X.columns[self.selector.get_support()]
        logger.info(f"Selected features: {selected_features.tolist()}")
        return selected_features.tolist()
