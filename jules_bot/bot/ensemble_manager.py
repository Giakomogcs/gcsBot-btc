# Ficheiro: src/core/ensemble_manager.py (VERSÃO FINAL)

import joblib
import pandas as pd
from pathlib import Path
import shap
import json

class EnsembleManager:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.models_dir = Path(self.config.data_paths.models_dir)
        self.specialists_config = self.config.trading_strategy.models.specialists
        self.ensemble_weights = self.config.trading_strategy.ensemble_weights
        
        self.models = self._load_all_models()
        self.explainers = {name: shap.TreeExplainer(model) for name, model in self.models.items()}

    def _load_all_models(self) -> dict:
        loaded_models = {}
        for specialist_name in self.specialists_config.keys():
            model_path = self.models_dir / f"{specialist_name}_model.joblib"
            if model_path.exists():
                try:
                    model = joblib.load(model_path)
                    self.logger.info(f"✅ Modelo para o especialista '{specialist_name}' carregado.")
                    loaded_models[specialist_name] = model
                except Exception as e:
                    self.logger.error(f"Falha ao carregar o modelo para '{specialist_name}': {e}")
            else:
                self.logger.warning(f"Modelo para '{specialist_name}' não encontrado.")
        return loaded_models

    def get_ensemble_signal(self, candle: pd.Series) -> dict:
        """
        Calcula a confiança do ensemble e gera um relatório de decisão.
        A decisão final de comprar ou não é delegada a outros componentes (PositionManager).
        """
        decision_report = {'signal': 'NEUTRAL'}
        if not self.models:
            return decision_report

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
                decision_report[name] = {'confidence': probability, 'weight': weight}
            except Exception as e:
                self.logger.error(f"Erro ao obter predição do modelo '{name}': {e}", exc_info=True)
                continue
        
        if total_weight == 0:
            return decision_report
            
        final_confidence = total_weighted_prob / total_weight
        decision_report['final_confidence'] = final_confidence
        
        # Lógica de sinal preliminar baseada em um limiar estático
        # A decisão final e mais complexa (grid, dca) fica no PositionManager
        static_threshold = self.config.trading_strategy.static_confidence_threshold
        if final_confidence >= static_threshold:
            decision_report['signal'] = 'BUY'
            shap_analysis = self.explain_decision(candle)
            decision_report['shap_analysis'] = shap_analysis

        self.logger.debug(f"Confiança do Ensemble: {final_confidence:.2%}. Limiar Estático: {static_threshold:.2%}. Sinal Preliminar: {decision_report['signal']}")

        return decision_report

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