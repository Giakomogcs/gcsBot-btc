# run_backtest.py (VERSÃO CORRIGIDA E INTEGRADA)

import warnings
import pandas as pd 
import logging

# Ignora TODOS os UserWarning (forma mais ampla)
warnings.filterwarnings("ignore", category=UserWarning)
# Configura o logger do LightGBM para mostrar apenas erros críticos
logging.getLogger('lightgbm').setLevel(logging.ERROR)
logging.getLogger('lightgbm').setLevel(logging.WARNING)

# Silencia avisos para um output limpo
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*bagging_fraction is set.*")
warnings.filterwarnings("ignore", message=".*feature_fraction is set.*")

# --- INÍCIO DA MODIFICAÇÃO 1: Importar o gerenciador de configurações ---
from src.config_manager import settings
# --- FIM DA MODIFICAÇÃO 1 ---

from src.data_manager import DataManager
from src.core.ensemble_manager import EnsembleManager
from src.core.backtester import Backtester
from src.core.position_manager import PositionManager # Importar o novo PositionManager
from src.logger import logger

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST ---")
    
    data_manager = DataManager()
    
    # Carrega a tabela principal de features
    df_features = data_manager.read_data_from_influx(
        measurement="features_master_table",
        start_date=settings.backtest.start_date  # Usando data do config
    ) 
    
    if df_features.empty:
        logger.error("Nenhuma feature foi carregada da 'features_master_table'. Execute o data_pipeline primeiro.")
        return

    # --- INÍCIO DA MODIFICAÇÃO 2: Instanciar os módulos com o config ---
    # O EnsembleManager agora recebe o dicionário de configurações completo
    ensemble_manager = EnsembleManager(config=settings) 
    
    if not ensemble_manager.models:
        logger.error("Nenhum especialista foi carregado. Execute o otimizador primeiro.")
        return
    
    # O Backtester também é inicializado com a configuração e o ensemble já pronto
    backtester = Backtester(
        config=settings, 
        data=df_features, 
        ensemble_manager=ensemble_manager
    )
    
    # Executa o backtest
    trades_df = backtester.run()

    # Salva o DataFrame de trades para análise futura
    if not trades_df.empty:
        trades_filepath = "data/output/trades_history.csv"
        trades_df.to_csv(trades_filepath, index=False)
        logger.info(f"Histórico de trades salvo com sucesso em: {trades_filepath}")
    
    # Calcula e exibe as métricas
    metrics = backtester.calculate_metrics(trades_df)
    
    print("\n--- MÉTRICAS DO BACKTEST ---")
    # Imprime as métricas de forma mais legível
    if isinstance(metrics, dict) and "message" in metrics:
        print(metrics["message"])
    else:
        for key, value in metrics.items():
            print(f"{key}: {value}")
    print("--------------------------\n")

if __name__ == "__main__":
    main()