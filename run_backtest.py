# Ficheiro: run_backtest.py (VERSÃO FINAL E ALINHADA)

from src.logger import logger
from src.config_manager import settings
from src.data_manager import DataManager
from src.core.ensemble_manager import EnsembleManager
from src.core.position_manager import PositionManager
from src.core.backtester import Backtester

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST (ARQUITETURA FINAL) ---")
    
    # --- 1. CARREGA OS COMPONENTES AUTÓNOMOS ---
    # Cada gestor agora é responsável pela sua própria inicialização e conexões.
    data_manager = DataManager()
    ensemble_manager = EnsembleManager(config=settings)
    position_manager = PositionManager(config=settings)
    
    # Limpa o histórico de trades para uma simulação limpa
    logger.info("Limpando o histórico de trades antigos...")
    # Acessamos o db_manager através da instância do position_manager para a limpeza
    position_manager.db_manager.client.delete_api().delete(
        "1970-01-01T00:00:00Z",
        "2030-01-01T00:00:00Z",
        f'_measurement="{position_manager.db_manager.measurement_name}"',
        bucket=position_manager.db_manager.bucket,
        org=position_manager.db_manager.org
    )
    
    # --- 2. EXECUÇÃO DO BACKTEST ---
    df_features = data_manager.read_data_from_influx(
        measurement="features_master_table",
        start_date=settings.backtest.start_date
    )
    if df_features.empty:
        logger.error("Não foram encontrados dados para o backtest.")
        return

    backtester = Backtester(
        data=df_features,
        ensemble_manager = EnsembleManager(config=settings),
        position_manager=position_manager
    )
    backtester.run()

if __name__ == "__main__":
    main()