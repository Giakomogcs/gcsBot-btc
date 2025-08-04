# run_optimizer.py (NOVO ARQUIVO)

import os
import joblib
import pandas as pd
from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.data.data_manager import DataManager
from gcs_bot.core.optimizer import Optimizer
from gcs_bot.core.model_trainer import ModelTrainer

def main():
    """
    Script principal para orquestrar o processo completo de treino de todos os modelos.
    """
    logger.info("--- INICIANDO PROCESSO DE TREINAMENTO DE MODELOS DE IA ---")
    
    # 1. Carregar os dados da fonte da verdade
    data_manager = DataManager()
    df_features = data_manager.read_data_from_influx(
        measurement="features_master_table",
        start_date="-2y" # Carrega 2 anos de dados para o treino
    )
    if df_features.empty:
        logger.error("A 'features_master_table' está vazia. Execute o data_pipeline primeiro.")
        return

    # Garante que a pasta de modelos existe
    models_dir = settings.data_paths.models_dir
    os.makedirs(models_dir, exist_ok=True)
    
    # 2. Iterar sobre cada especialista definido no config.yml
    for specialist_name, specialist_config in settings.trading_strategy.models.specialists.items():
        
        # Otimiza para encontrar os melhores parâmetros
        optimizer = Optimizer(
            data=df_features,
            specialist_name=specialist_name,
            specialist_features=specialist_config.features,
            n_trials=settings.optimizer.n_trials
        )
        best_params = optimizer.run()
        
        # Treina o modelo final com os melhores parâmetros usando TODOS os dados
        logger.info(f"Treinando modelo final para '{specialist_name}' com os melhores parâmetros...")
        final_trainer = ModelTrainer(params=best_params, features=specialist_config.features)
        final_model, final_scaler = final_trainer.train(df_features)
        
        # Salva o modelo e o scaler no disco
        model_path = os.path.join(models_dir, f"{specialist_name}_model.joblib")
        scaler_path = os.path.join(models_dir, f"{specialist_name}_scaler.joblib")
        
        joblib.dump(final_model, model_path)
        joblib.dump(final_scaler, scaler_path)
        
        logger.info(f"✅ Modelo e Scaler para '{specialist_name}' salvos com sucesso!")

if __name__ == "__main__":
    main()