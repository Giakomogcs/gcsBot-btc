# src/core/ensemble_manager.py (VERSÃO CORRIGIDA E COMPLETA)

import joblib
import os
import json
import pandas as pd
from typing import Tuple, Dict, Any, Optional

from src.logger import logger
from src.config_manager import settings

class EnsembleManager:
    """
    Gerencia o carregamento e a utilização de múltiplos modelos de IA (especialistas)
    para gerar um sinal de trading consolidado.
    """
    def __init__(self):
        logger.info("EnsembleManager inicializado.")
        # --- INÍCIO DA CORREÇÃO ---
        # Inicializa os atributos e chama o método de carregamento
        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, Any] = {}
        self.features: Dict[str, list[str]] = {}
        self.weights = settings.trading_strategy.ensemble_weights

        self._load_all_models()
        # --- FIM DA CORREÇÃO ---

    def _load_all_models(self):
        """
        Carrega todos os modelos de especialistas, scalers e listas de features
        definidos no arquivo de configuração.
        """
        logger.info("Carregando modelos de especialistas do Ensemble...")
        models_dir = settings.data_paths.models_dir
        
        # Itera sobre cada especialista definido no config.yml
        for specialist_name, specialist_config in settings.trading_strategy.models.specialists.items():
            model_path = os.path.join(models_dir, f"{specialist_name}_model.joblib")
            scaler_path = os.path.join(models_dir, f"{specialist_name}_scaler.joblib")
            
            # Verifica se os arquivos do modelo e do scaler existem
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                try:
                    self.models[specialist_name] = joblib.load(model_path)
                    self.scalers[specialist_name] = joblib.load(scaler_path)
                    self.features[specialist_name] = specialist_config.features
                    logger.info(f"✅ Modelo especialista '{specialist_name}' carregado com sucesso.")
                except Exception as e:
                    logger.error(f"❌ Falha ao carregar o modelo '{specialist_name}': {e}")
            else:
                logger.warning(f"Arquivos de modelo/scaler para o especialista '{specialist_name}' não encontrados.")
        
        if not self.models:
            logger.error("Nenhum modelo de IA foi carregado. Execute o otimizador primeiro.")

    def get_prediction(self, candle_data: pd.Series) -> Tuple[float, Dict[str, Any]]:
        """
        Obtém a predição de todos os especialistas, combina-as usando os pesos
        configurados e retorna um sinal consolidado e a confiança.
        """
        if not self.models:
            return 0.0, {"signal": "HOLD", "reason": "Nenhum modelo carregado"}

        weighted_confidences = []
        individual_predictions = {}

        # Obtém a predição de cada especialista
        for name, model in self.models.items():
            scaler = self.scalers[name]
            features = self.features[name]
            
            # Garante que todas as features necessárias estão presentes nos dados da vela
            if not all(feature in candle_data for feature in features):
                logger.warning(f"Faltam features para o modelo '{name}'. A saltar a predição.")
                continue

            # Prepara os dados para o modelo
            input_data = pd.DataFrame([candle_data[features]])
            scaled_data = scaler.transform(input_data)
            
            # Obtém a probabilidade de compra (classe 1)
            confidence = model.predict_proba(scaled_data)[0][1]
            
            weight = self.weights.get(name, 0)
            weighted_confidences.append(confidence * weight)
            individual_predictions[name] = confidence

        # Calcula a confiança final ponderada
        final_confidence = sum(weighted_confidences) / sum(self.weights.values()) if self.weights else 0

        details = {
            "signal": "LONG" if final_confidence > settings.trading_strategy.confidence_threshold else "HOLD",
            "final_confidence": final_confidence,
            "individual_predictions": individual_predictions,
            "reason": f"Confiança ponderada {final_confidence:.2f} vs Limiar {settings.trading_strategy.confidence_threshold}"
        }

        return final_confidence, details