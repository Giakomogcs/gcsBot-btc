# Ficheiro: run_backtest.py (VERSÃO FINAL INTEGRADA)

import pandas as pd
from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.data.data_manager import DataManager
from gcs_bot.core.ensemble_manager import EnsembleManager
from gcs_bot.core.backtester import Backtester
from gcs_bot.core.position_manager import PositionManager
from gcs_bot.database.database_manager import db_manager
import sys

def main():
    logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST (MODO ALTA FIDELIDADE) ---")
    
    logger.info("Limpando o histórico de trades antigos do banco de dados para um backtest limpo...")
    start = "1970-01-01T00:00:00Z"
    stop = pd.Timestamp.now(tz='UTC').isoformat()
    db_manager._client.delete_api().delete(start, stop, '_measurement="trades"', bucket=settings.database.bucket, org=settings.database.org)
    logger.info("✅ Histórico de trades limpo.")
    
    data_manager = DataManager()
    df_features = data_manager.read_data_from_influx(
        measurement="features_master_table",
        start_date=settings.backtest.start_date
    )

    if df_features.empty:
        logger.error("A 'features_master_table' está vazia ou não pôde ser carregada.")
        return

    ensemble_manager = EnsembleManager()
    if not ensemble_manager.models:
        logger.error("Nenhum modelo de IA foi carregado. Execute o otimizador primeiro.")
        return

    position_manager = PositionManager(settings)

    backtester = Backtester(
        data=df_features, 
        ensemble_manager=ensemble_manager,
        position_manager=position_manager
    )
    
    backtester.run()

if __name__ == "__main__":
    main()