import pandas as pd
import sys
import os
import argparse

# Adiciona a raiz do projeto ao path para que o jules_bot seja encontrável
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import settings
from jules_bot.database.database_manager import DatabaseManager

def main(environment: str):
    try:
        logger.info(f"--- LIMPANDO A MEDIÇÃO 'TRADES' DO AMBIENTE '{environment}' ---")

        # A instanciação do DatabaseManager não é estritamente necessária aqui,
        # pois usamos o _client diretamente, mas é bom para consistência.
        # No futuro, o método de delete pode ser movido para dentro da classe.
        db_manager = DatabaseManager(execution_mode=environment)

        start = "1970-01-01T00:00:00Z"
        stop = pd.Timestamp.now(tz='UTC').isoformat()

        # PREDICADO DE EXCLUSÃO: Agora inclui o ambiente para segurança.
        predicate = f'_measurement="trades" AND environment="{environment}"'

        logger.info(f"Excluindo dados com o predicado: '{predicate}' do bucket '{settings.database.bucket}'...")
        db_manager._client.delete_api().delete(start, stop, predicate, bucket=settings.database.bucket, org=settings.database.org)
        logger.info(f"✅ Medição 'trades' do ambiente '{environment}' limpa com sucesso.")

    except Exception as e:
        logger.error("--- ❌ ERRO CRÍTICO DURANTE A LIMPEZA DA MEDIÇÃO 'TRADES' ❌ ---")
        logger.error(f"Ocorreu um erro inesperado: {e}", exc_info=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Limpa a medição 'trades' de um ambiente específico no InfluxDB."
    )
    parser.add_argument(
        '--env',
        type=str,
        required=True,
        choices=['trade', 'test', 'backtest'],
        help='O ambiente de execução para limpar (trade, test, backtest). Este argumento é obrigatório por segurança.'
    )
    args = parser.parse_args()

    main(environment=args.env)
