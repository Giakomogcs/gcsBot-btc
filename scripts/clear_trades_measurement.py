import pandas as pd
import sys
import os

# Adiciona a raiz do projeto ao path para que o gcs_bot seja encontrável
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.database.database_manager import db_manager

def main():
    try:
        logger.info("--- LIMPANDO A MEDIÇÃO 'TRADES' DO BANCO DE DADOS ---")

        start = "1970-01-01T00:00:00Z"
        stop = pd.Timestamp.now(tz='UTC').isoformat()

        logger.info(f"Excluindo dados da medição 'trades' do bucket '{settings.database.bucket}'...")
        db_manager._client.delete_api().delete(start, stop, '_measurement="trades"', bucket=settings.database.bucket, org=settings.database.org)
        logger.info("✅ Medição 'trades' limpa com sucesso.")

    except Exception as e:
        logger.error("--- ❌ ERRO CRÍTICO DURANTE A LIMPEZA DA MEDIÇÃO 'TRADES' ❌ ---")
        logger.error(f"Ocorreu um erro inesperado: {e}", exc_info=True)

if __name__ == "__main__":
    main()
