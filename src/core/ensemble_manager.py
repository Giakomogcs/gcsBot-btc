# Ficheiro: src/core/ensemble_manager.py (VERSÃO FINAL)

import joblib
import pandas as pd
from pathlib import Path
import shap
import json

from src.logger import logger
from src.config_manager import settings
from src.core.confidence_manager import ConfidenceManager # <-- NOVA IMPORTAÇÃO

class EnsembleManager:
    def __init__(self):
        # ... (o __init__ permanece o mesmo, mas adicionamos o confidence_manager)
        self.models_dir = Path(settings.data_paths.models_dir)
        self.specialists_config = settings.trading_strategy.models.specialists
        self.ensemble_weights = settings.trading_strategy.ensemble_weights
        
        # --- MUDANÇA CRÍTICA ---
        # O EnsembleManager agora tem o seu próprio gestor de confiança
        self.confidence_manager = ConfidenceManager()
        
        self.models = self._load_all_models()
        self.explainers = {name: shap.TreeExplainer(model) for name, model in self.models.items()}

    def _load_all_models(self) -> dict:
        # ... (esta função permanece exatamente igual)
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

    def get_ensemble_signal(self, candle: pd.Series) -> tuple[str, dict]:
        """
        Calcula o sinal final e, se for um BUY, gera um relatório de decisão detalhado.
        """
        if not self.models:
            return "NEUTRAL", {}

        total_weighted_prob = 0.0
        total_weight = 0.0
        decision_report = {}

        for name, model in self.models.items():
            # ... (a lógica de cálculo da probabilidade permanece a mesma)
            weight = self.ensemble_weights.get(name, 0)
            if weight == 0: continue
            try:
                required_features = self.specialists_config[name].features
                X = pd.DataFrame([candle[required_features]])
                probability = model.predict_proba(X)[0][1]
                total_weighted_prob += probability * weight
                total_weight += weight
                decision_report[name] = {'confidence': probability, 'weight': weight}
            except Exception:
                continue
        
        if total_weight == 0:
            return "NEUTRAL", {}
            
        final_confidence = total_weighted_prob / total_weight
        decision_report['final_confidence'] = final_confidence
        
        # --- LÓGICA DE DECISÃO ATUALIZADA ---
        # 1. Pergunta ao ConfidenceManager qual é o limiar para AGORA
        current_threshold = self.confidence_manager.get_current_threshold(candle)
        decision_report['required_confidence'] = current_threshold
        
        logger.info(f"Confiança combinada: {final_confidence:.2%}. Limiar necessário para o regime atual: {current_threshold:.2%}")

        # 2. Compara a confiança do comitê com o limiar dinâmico
        if final_confidence >= current_threshold:
            shap_analysis = self.explain_decision(candle)
            decision_report['shap_analysis'] = shap_analysis
            return "BUY", decision_report
        else:
            return "NEUTRAL", {}

    def explain_decision(self, candle: pd.Series) -> dict:
        # ... (esta função permanece exatamente igual)
        full_analysis = {}
        for name, explainer in self.explainers.items():
            try:
                required_features = self.specialists_config[name].features
                instance_df = pd.DataFrame([candle[required_features]])
                shap_values = explainer.shap_values(instance_df)[1][0]
                feature_impact = {feature: value for feature, value in zip(instance_df.columns, shap_values)}
                full_analysis[name] = feature_impact
            except Exception as e:
                logger.warning(f"Não foi possível gerar a análise SHAP para o especialista '{name}': {e}")
        return full_analysis