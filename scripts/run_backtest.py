# Ficheiro: run_backtest.py (VERSÃO FINAL INTEGRADA)

import pandas as pd
import sys
import os

# Adiciona a raiz do projeto ao path para que o gcs_bot seja encontrável
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.data.data_manager import DataManager
from gcs_bot.core.ensemble_manager import EnsembleManager
from gcs_bot.core.backtester import Backtester
from gcs_bot.core.position_manager import PositionManager
from gcs_bot.database.database_manager import db_manager
import sys

def main():
    try:
        logger.info("--- INICIANDO LABORATÓRIO DE BACKTEST (MODO ALTA FIDELIDADE) ---")

        logger.info("Limpando o histórico de trades antigos do banco de dados para um backtest limpo...")
        start = "1970-01-01T00:00:00Z"
        stop = pd.Timestamp.now(tz='UTC').isoformat()
        db_manager._client.delete_api().delete(start, stop, '_measurement="trades"', bucket=settings.database.bucket, org=settings.database.org)
        logger.info("✅ Histórico de trades limpo.")

        # --- Master Builder: Instanciando e Injetando Dependências ---
        logger.info("Construindo o ambiente do backtest com injeção de dependências...")

        data_manager = DataManager(db_manager=db_manager, config=settings, logger=logger)

        df_features = data_manager.read_data_from_influx(
            measurement="features_master_table",
            start_date=settings.backtest.start_date
        )

        if df_features.empty:
            logger.error("A 'features_master_table' está vazia ou não pôde ser carregada. Abortando backtest.")
            return

        ensemble_manager = EnsembleManager(config=settings, logger=logger)
        if not ensemble_manager.models:
            logger.error("Nenhum modelo de IA foi carregado. Execute o otimizador primeiro. Abortando backtest.")
            return

        position_manager = PositionManager(config=settings, db_manager=db_manager, logger=logger)

        backtester = Backtester(
            data=df_features,
            ensemble_manager=ensemble_manager,
            position_manager=position_manager,
            config=settings,
            logger=logger
        )

        backtester.run()

    except Exception as e:
        logger.error("--- ❌ ERRO CRÍTICO DURANTE O BACKTEST ❌ ---")
        # Log da exceção completa para debug
        logger.error(f"Ocorreu um erro inesperado: {e}", exc_info=True)

        # Análise da Causa Provável para o Usuário
        if "Failed to resolve 'db'" in str(e) or "Name or service not known" in str(e):
            logger.error("\n--- CAUSA PROVÁVEL ---")
            logger.error("Este erro geralmente significa que o script não consegue se conectar ao banco de dados porque não está sendo executado dentro do ambiente Docker.")
            logger.error("Para corrigir, certifique-se de que os containers Docker estão ativos e execute o backtest usando o script de gerenciamento:")
            logger.error("Comando Sugerido: .\\manage.ps1 backtest")

if __name__ == "__main__":
    main()