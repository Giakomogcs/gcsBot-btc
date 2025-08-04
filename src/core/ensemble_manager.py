# Ficheiro: src/core/ensemble_manager.py (VERSÃO FINAL COM ARQUITETURA CORRETA)

import joblib
import pandas as pd
from pathlib import Path
import shap
import json

from src.logger import logger
# A importação global do 'settings' desaparece daqui

class EnsembleManager:
    # --- MUDANÇA CRÍTICA NO CONSTRUTOR ---
    def __init__(self, config):
        self.config = config # Recebe e armazena a configuração
        self.models_dir = Path(self.config.data_paths.models_dir)
        self.specialists_config = self.config.trading_strategy.models.specialists
        self.ensemble_weights = self.config.trading_strategy.ensemble_weights
        self.confidence_threshold = self.config.trading_strategy.confidence_threshold
        
        self.models = self._load_all_models()
        self.explainers = {name: shap.TreeExplainer(model) for name, model in self.models.items()}

    def _load_all_models(self) -> dict:
        loaded_models = {}
        for specialist_name in self.specialists_config.keys():
            model_path = self.models_dir / f"{specialist_name}_model.joblib"
            if model_path.exists():
                try:
                    model = joblib.load(model_path)
                    logger.info(f"✅ Modelo para o especialista '{specialist_name}' carregado.")
                    loaded_models[specialist_name] = model
                except Exception as e:
                    logger.error(f"Falha ao carregar o modelo para '{specialist_name}': {e}")
            else:
                logger.warning(f"Modelo para '{specialist_name}' não encontrado.")
        return loaded_models

    def get_ensemble_signal(self, candle: pd.Series) -> tuple[str, float]:
        """
        Calcula o sinal final e a confiança combinada.
        Retorna: (sinal, confiança_final)
        """
        if not self.models:
            return "NEUTRAL", 0.0

        total_weighted_prob = 0.0
        total_weight = 0.0

        for name, model in self.models.items():
            weight = self.ensemble_weights.get(name, 0)
            if weight == 0: continue
            try:
                required_features = self.specialists_config[name].features
                X = pd.DataFrame([candle[required_features]])
                probability = model.predict_proba(X)[0][1]
                total_weighted_prob += probability * weight
                total_weight += weight
            except Exception:
                continue
        
        if total_weight == 0:
            return "NEUTRAL", 0.0
            
        final_confidence = total_weighted_prob / total_weight
        
        logger.info(f"Confiança combinada do comitê: {final_confidence:.2%}")

        if final_confidence >= self.confidence_threshold:
            return "BUY", final_confidence
        else:
            return "NEUTRAL", final_confidence

    # A função de explicação SHAP pode ser adicionada mais tarde,
    # vamos focar-nos em fazer o backtest funcionar primeiro.