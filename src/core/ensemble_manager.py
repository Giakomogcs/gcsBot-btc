import pandas as pd
import joblib
import os
from src.config_manager import settings
from src.logger import logger

class EnsembleManager:
    def __init__(self):
        # O manager agora começa "vazio", sem modelos pré-carregados.
        self.weights = settings.trading_strategy.ensemble_weights
        self.specialists_config = settings.trading_strategy.models.specialists
        
        # O caminho base para todos os modelos vem da ÚNICA fonte da verdade
        self.base_models_path = settings.data_paths.models_dir
        
        # Cache para guardar os modelos de cada regime já carregados, evitando leituras de disco repetidas
        self._loaded_models_cache = {}
        logger.info("EnsembleManager inicializado em modo dinâmico (camaleão).")

    def _load_models_for_regime(self, regime_id: int) -> dict:
        """
        Carrega (e guarda em cache) a equipa de especialistas para um regime específico.
        """
        regime_id = int(regime_id)
        if regime_id in self._loaded_models_cache:
            return self._loaded_models_cache[regime_id]

        logger.debug(f"Carregando equipa de especialistas para o regime {regime_id}...")
        
        # Constrói o caminho para a pasta do regime específico
        regime_path = os.path.join(self.base_models_path, f"regime_{regime_id}")
        
        models = {}
        if not os.path.isdir(regime_path):
            logger.warning(f"Diretório de modelos não encontrado para o regime {regime_id} em: {regime_path}. Usando modelos 'all_data'.")
            regime_path = os.path.join(self.base_models_path, "all_data") # Fallback para modelos genéricos

        for model_name in self.specialists_config.keys():
            # O nome do ficheiro é padronizado
            model_file = os.path.join(regime_path, f"model_{model_name}.joblib")
            if os.path.exists(model_file):
                models[model_name] = joblib.load(model_file)
            else:
                logger.warning(f"Modelo para '{model_name}' não encontrado no regime {regime_id}.")
        
        if models:
            self._loaded_models_cache[regime_id] = models
        
        return models

    def get_prediction(self, data_slice: pd.DataFrame):
        """
        Gera uma previsão baseada no regime de mercado da vela mais recente.
        """
        latest_candle = data_slice.iloc[-1]
        
        # 1. Diagnosticar o regime da situação atual
        if 'market_regime' not in latest_candle or latest_candle['market_regime'] == -1:
            logger.debug("Regime de mercado não identificado. Nenhuma previsão será feita.")
            return 0.0, {'signal': 'HOLD', 'details': {}}
            
        current_regime = int(latest_candle['market_regime'])

        # 2. Carregar a equipa de especialistas correta para o regime
        regime_models = self._load_models_for_regime(current_regime)

        if not regime_models:
            logger.warning(f"Nenhum modelo disponível para o regime {current_regime}. Nenhuma previsão será feita.")
            return 0.0, {'signal': 'HOLD', 'details': {}}

        # 3. Gerar a previsão usando a equipa carregada
        total_weighted_confidence = 0
        total_weights = 0
        specialist_predictions = {}

        for model_name, model in regime_models.items():
            specialist_info = self.specialists_config.get(model_name)
            if not specialist_info: continue

            features_for_model = specialist_info.features
            if not all(feature in latest_candle.index for feature in features_for_model):
                logger.warning(f"Features faltando para '{model_name}' no regime {current_regime}.")
                continue

            prediction_proba = model.predict_proba(latest_candle[features_for_model].values.reshape(1, -1))[0]
            confidence = prediction_proba.max()
            predicted_class = prediction_proba.argmax()
            
            specialist_predictions[model_name] = {'confidence': confidence, 'predicted_class': predicted_class}
            weight = self.weights.get(model_name, 0)
            
            if predicted_class == 1:
                total_weighted_confidence += confidence * weight
            else: # Inclui a classe 0 (não-compra)
                total_weighted_confidence -= confidence * weight
            total_weights += weight

        if total_weights == 0:
            return 0.0, {'signal': 'HOLD', 'details': specialist_predictions}

        final_confidence = abs(total_weighted_confidence / total_weights)
        signal = 'LONG' if total_weighted_confidence > 0 else 'SHORT'
            
        prediction_details = {'signal': signal, 'details': specialist_predictions}
        return final_confidence, prediction_details