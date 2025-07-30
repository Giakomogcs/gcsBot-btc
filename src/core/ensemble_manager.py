import pandas as pd
import joblib
import os
# A importação e o uso de 'logging' foram removidos daqui

class EnsembleManager:
    def __init__(self, config):
        self.config = config.trading_strategy
        self.models_config = self.config.models
        self.weights = self.config.ensemble_weights
        self.models = self._load_models()

    def _load_models(self):
        models = {}
        models_path = self.models_config.models_path
        specialists_info = self.models_config.specialists
        for model_name, model_info in specialists_info.items():
            model_file = os.path.join(models_path, model_info.filename)
            if os.path.exists(model_file):
                print(f"Carregando modelo especialista: {model_name} de {model_file}")
                models[model_name] = joblib.load(model_file)
            else:
                print(f"AVISO: Arquivo do modelo não encontrado para {model_name}: {model_file}")
        return models

    def get_prediction(self, data_slice):
        if not self.models:
            return 0.0, {'signal': 'HOLD', 'details': {}}

        latest_features = data_slice.iloc[-1:]
        
        total_weighted_confidence = 0
        total_weights = 0
        specialist_predictions = {}

        # O bloco try/finally foi removido daqui
        for model_name, model in self.models.items():
            features_for_model = self.models_config.specialists[model_name].features

            if not all(feature in latest_features.columns for feature in features_for_model):
                print(f"AVISO: Features faltando para o modelo {model_name}. Pulando a previsão.")
                continue

            prediction_proba = model.predict_proba(latest_features[features_for_model])[0]
            
            confidence = prediction_proba.max()
            predicted_class = prediction_proba.argmax()
            
            specialist_predictions[model_name] = {
                'confidence': confidence,
                'predicted_class': predicted_class
            }

            weight = self.weights.get(model_name, 0)
            
            if confidence > 0.5:
                if predicted_class == 1:
                    total_weighted_confidence += confidence * weight
                else:
                    total_weighted_confidence -= confidence * weight
                total_weights += weight

        if total_weights == 0:
            final_confidence = 0
        else:
            final_confidence = abs(total_weighted_confidence / total_weights)

        if total_weighted_confidence > 0:
            signal = 'LONG'
        elif total_weighted_confidence < 0:
            signal = 'SHORT'
        else:
            signal = 'HOLD'
            
        prediction_details = {
            'signal': signal,
            'details': specialist_predictions
        }

        return final_confidence, prediction_details