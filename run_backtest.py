# run_backtest.py (VERSÃO FINAL COM IA)

import pandas as pd
from src.logger import logger
from src.config_manager import settings
from src.data_manager import DataManager
from src.core.ensemble_manager import EnsembleManager
from src.core.backtester import Backtester
import sys

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST COM IA ---")
    
    data_manager = DataManager()
    df_features = data_manager.read_data_from_influx(
        measurement="features_master_table",
        start_date=settings.backtest.start_date
    )

    if df_features.empty:
        logger.error("A 'features_master_table' está vazia ou não pôde ser carregada.")
        return

    # 1. Carrega o EnsembleManager, que por sua vez carrega os modelos de IA
    ensemble_manager = EnsembleManager()
    if not ensemble_manager.models: # Verifica se algum modelo foi carregado
        logger.error("Nenhum modelo de IA foi carregado pelo EnsembleManager. Execute o otimizador primeiro.")
        return

    # 2. Instancia o Backtester, agora passando o ensemble_manager
    backtester = Backtester(
        data=df_features, 
        ensemble_manager=ensemble_manager
    )
    
    backtester.run()

if __name__ == "__main__":
    main()