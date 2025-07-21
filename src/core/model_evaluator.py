import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
)
from src.logger import logger

class ModelEvaluator:
    def __init__(self, model, scaler, data, feature_names, labels):
        self.model = model
        self.scaler = scaler
        self.data = data
        self.feature_names = feature_names
        self.labels = labels

    def evaluate(self):
        X = self.data[self.feature_names]
        X_scaled = self.scaler.transform(X)
        y_pred = self.model.predict(X_scaled)
        y_pred_proba = self.model.predict_proba(X_scaled)[:, 1]

        metrics = {
            "accuracy": accuracy_score(self.labels, y_pred),
            "precision": precision_score(self.labels, y_pred),
            "recall": recall_score(self.labels, y_pred),
            "f1_score": f1_score(self.labels, y_pred),
            "roc_auc": roc_auc_score(self.labels, y_pred_proba),
        }

        logger.info("Model Evaluation Metrics:")
        for metric, value in metrics.items():
            logger.info(f"  - {metric}: {value:.4f}")

        cm = confusion_matrix(self.labels, y_pred)
        logger.info("Confusion Matrix:")
        logger.info(f"\n{cm}")

        return metrics, cm
