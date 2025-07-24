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

from src.core.data_manager import DataManager
from src.core.ensemble_manager import EnsembleManager
from src.core.backtester import Backtester
from src.logger import logger

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST ---")
    
    # 1. Carrega os dados e calcula as features
    #    Vamos usar o pipeline completo para garantir consistência
    logger.info("Executando o pipeline de dados para garantir que a base de dados está pronta...")
    data_manager = DataManager()
    df_features = data_manager.run_data_pipeline(symbol='BTCUSDT', interval='1m')

    if df_features is None or df_features.empty:
        logger.error("O pipeline de dados não retornou dados. Backtest abortado.")
        return
        
    # 2. Instancia o Maestro
    ensemble = EnsembleManager(situation_name="all_data")
    if not ensemble.specialists:
        logger.error("Nenhum especialista foi carregado. Execute o otimizador primeiro. Backtest não pode continuar.")
        return
        
    # 3. Instancia e executa o Backtester
    #    Pegamos apenas os últimos 6 meses (aprox. 262800 velas de 1m) para o backtest
    backtest_data = df_features.tail(262800)
    logger.info(f"Executando backtest em {len(backtest_data)} velas (aprox. 6 meses)...")
    
    backtester = Backtester(data=backtest_data, ensemble=ensemble)
    backtester.run()

if __name__ == '__main__':
    main()