# run_backtest.py

import os, sys
import warnings
from sklearn.exceptions import UserWarning

# Silencia os avisos diretamente no script para garantir um output limpo
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*bagging_fraction is set.*")
warnings.filterwarnings("ignore", message=".*feature_fraction is set.*")
warnings.filterwarnings("ignore", message=".*lambda_l1 is set.*")
warnings.filterwarnings("ignore", message=".*lambda_l2 is set.*")
warnings.filterwarnings("ignore", message=".*bagging_freq is set.*")


from src.core.data_manager import DataManager
from src.core.feature_engineering import add_all_features
from src.core.ensemble_manager import EnsembleManager
from src.core.backtester import Backtester
from src.config_manager import settings
from src.logger import logger

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST ---")
    
    # 1. Carrega os dados e calcula as features
    data_manager = DataManager()
    df_full = data_manager.read_data_from_influx("btc_btcusdt_1m", "-180d") # 6 meses para um teste robusto
    if df_full.empty:
        logger.error("Nenhum dado carregado. Teste abortado.")
        return

    df_features = add_all_features(df_full)
    
    # 2. Instancia o Maestro
    ensemble = EnsembleManager(situation_name="all_data")
    if not ensemble.specialists:
        logger.error("Nenhum especialista foi carregado. Execute o otimizador primeiro. Backtest não pode continuar.")
        return
        
    # 3. Instancia e executa o Backtester
    backtester = Backtester(data=df_features, ensemble=ensemble)
    backtester.run()

if __name__ == '__main__':
    # Adiciona a raiz do projeto ao path para garantir que as importações funcionem
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    main()