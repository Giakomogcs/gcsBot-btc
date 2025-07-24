# src/core/ensemble_manager.py

import os
import joblib
import pandas as pd
import numpy as np
from collections import deque
import json
import re # Importado para extrair o nome do especialista

# Resolução de Path
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logger import logger
from src.config_manager import settings

class EnsembleManager:
    """
    O "Maestro" da Mente-Colmeia.
    Carrega, avalia e combina as previsões de múltiplos especialistas de forma dinâmica.
    """
    def __init__(self, situation_name: str = "all_data"):
        self.situation_name = situation_name
        self.specialists = {}
        self.performance_history = {}
        self._load_specialists()

    def _load_specialists(self):
        """
        Carrega os artefactos de todos os especialistas que encontrar na pasta da situação.
        """
        situation_path = os.path.join(settings.data_paths.data_dir, self.situation_name)
        if not os.path.exists(situation_path):
            logger.error(f"Diretório para a situação '{self.situation_name}' não encontrado.")
            return

        # <<< --- LÓGICA DE DESCOBERTA DINÂMICA --- >>>
        # Procura por todos os ficheiros de modelo que sigam o padrão
        model_files = [f for f in os.listdir(situation_path) if f.startswith('model_') and f.endswith('.joblib')]

        if not model_files:
            logger.warning(f"Nenhum ficheiro de modelo encontrado em '{situation_path}'.")
            return

        for model_file in model_files:
            # Extrai o nome do especialista do nome do ficheiro (ex: de 'model_price_action.joblib' extrai 'price_action')
            match = re.search(r'model_(.+)\.joblib', model_file)
            if not match: continue
            
            name = match.group(1)
            model_path = os.path.join(situation_path, model_file)
            scaler_path = os.path.join(situation_path, f"scaler_{name}.joblib")
            params_path = os.path.join(situation_path, f"params_{name}.json") # Precisamos das features

            if os.path.exists(scaler_path) and os.path.exists(params_path):
                logger.info(f"Carregando especialista '{name}'...")
                with open(params_path, 'r') as f:
                    params_data = json.load(f)

                self.specialists[name] = {
                    "model": joblib.load(model_path),
                    "scaler": joblib.load(scaler_path),
                    "feature_names": params_data.get("feature_names", []) # Carrega as features que o modelo usa
                }
                self.performance_history[name] = deque(maxlen=50)
                logger.info(f" -> ✅ Especialista '{name}' carregado com sucesso.")
            else:
                logger.warning(f"Faltam artefactos (scaler ou params) para o especialista '{name}'. Ele será ignorado.")

    # ... (O resto do ficheiro: update_performance, _get_performance_weights, get_consensus_signal continua igual) ...
    def update_performance(self, specialist_name: str, pnl: float):
        if specialist_name in self.performance_history:
            self.performance_history[specialist_name].append(pnl)

    def _get_performance_weights(self) -> dict:
        weights = {}
        for name, history in self.performance_history.items():
            if len(history) < 10:
                weights[name] = 1.0
                continue
            
            history_np = np.array(history)
            mean_pnl = np.mean(history_np)
            std_pnl = np.std(history_np)

            if std_pnl > 0 and mean_pnl > 0:
                sharpe = mean_pnl / std_pnl
                weights[name] = 1.0 + sharpe
            else:
                weights[name] = 0.5
        
        return weights

    def get_consensus_signal(self, current_features: pd.DataFrame) -> tuple[int, float]:
        """
        Obtém a previsão de cada especialista, pondera e retorna um sinal e a confiança.
        Retorna: (sinal, pontuacao_final_de_confianca)
        Sinal: 1 para COMPRA, 0 para MANTER.
        """
        if not self.specialists:
            logger.warning("Nenhum especialista carregado. Impossível gerar sinal.")
            return 0, 0.0

        weights = self._get_performance_weights()
        final_score = 0
        total_weight = 0

        for name, specialist in self.specialists.items():
            model_features = specialist['feature_names']
            
            if not all(feat in current_features.columns for feat in model_features):
                logger.error(f"Faltam features para o especialista '{name}'. Sinal não pode ser gerado.")
                return 0, 0.0
            
            X = current_features[model_features]
            
            X_scaled = specialist['scaler'].transform(X.values)
            confidence = specialist['model'].predict_proba(X_scaled, verbose=-1)[0][1]
            
            specialist_weight = weights.get(name, 1.0)
            final_score += confidence * specialist_weight
            total_weight += specialist_weight
        
        if total_weight > 0:
            final_score /= total_weight
        else:
            final_score = 0.0

        signal = 1 if final_score > settings.execution.confidence_threshold else 0
        
        return signal, final_score


if __name__ == '__main__':
    # O Ponto de Entrada para Teste continua igual
    logger.info("--- Testando o EnsembleManager (Versão Flexível) ---")
    
    from src.core.data_manager import DataManager
    from src.core.feature_engineering import add_all_features

    settings.influxdb_bucket = "btc_data"
    
    data_manager = DataManager()
    df_full = data_manager.read_data_from_influx("btc_btcusdt_1m", "-2d")
    if df_full.empty:
        logger.error("Nenhum dado carregado. Teste abortado.")
    else:
        df_features = add_all_features(df_full)
        
        ensemble = EnsembleManager(situation_name="all_data")
        
        if ensemble.specialists: # Só executa o teste se encontrou algum especialista
            ensemble.update_performance("price_action", 0.01) # Simula um resultado para o único especialista que temos

            last_candle_features = df_features.tail(1)
            
            logger.info("\n--- Pedindo Sinal de Consenso para a Última Vela ---")
            signal, confidences = ensemble.get_consensus_signal(last_candle_features)
            
            print("\n--- RESULTADO DO TESTE ---")
            print(f"Especialistas Encontrados e Carregados: {list(ensemble.specialists.keys())}")
            print(f"Pesos de Performance Calculados: {ensemble._get_performance_weights()}")
            print(f"Confianças Individuais dos Especialistas: {confidences}")
            print(f"Sinal Final da Mente-Colmeia: {'COMPRA' if signal == 1 else 'MANTER'}")
            print("--------------------------")
        else:
            logger.error("Nenhum modelo especialista foi encontrado na pasta 'data/all_data'. Teste não pôde ser concluído.")