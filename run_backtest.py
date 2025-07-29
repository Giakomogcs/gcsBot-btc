# run_backtest.py (VERSÃO CORRIGIDA)

import os
import sys
import warnings
# A linha "from sklearn.exceptions import UserWarning" foi REMOVIDA.

# Silencia os avisos diretamente no script para garantir um output limpo.
# O Python já conhece "UserWarning" por defeito.
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*bagging_fraction is set.*")
warnings.filterwarnings("ignore", message=".*feature_fraction is set.*")
warnings.filterwarnings("ignore", message=".*lambda_l1 is set.*")
warnings.filterwarnings("ignore", message=".*lambda_l2 is set.*")
warnings.filterwarnings("ignore", message=".*bagging_freq is set.*")

from src.data_manager import DataManager
from src.core.ensemble_manager import EnsembleManager
from src.core.backtester import Backtester
from src.logger import logger

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST ---")
    
    data_manager = DataManager()
    
    # O backtester agora lê diretamente da tabela de features processada
    df_features = data_manager.read_data_from_influx(
        measurement="features_master_table", # <<< MUDANÇA CRÍTICA AQUI
        start_date="-180d"
    ) 
    
    if df_features.empty:
        logger.error("Nenhuma feature foi carregada da 'features_master_table'. Execute o data_pipeline primeiro.")
        return

    ensemble = EnsembleManager(situation_name="all_data")
    if not ensemble.specialists:
        logger.error("Nenhum especialista foi carregado. Execute o otimizador primeiro.")
        return
        
    backtester = Backtester(data=df_features, ensemble=ensemble)
    backtester.run()

if __name__ == '__main__':
    main()