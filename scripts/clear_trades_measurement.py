import pandas as pd
import sys
import os
import argparse

# Adiciona a raiz do projeto ao path para que o jules_bot seja encontrável
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.database.database_manager import DatabaseManager

def main(environment: str):
    try:
        logger.info(f"--- LIMPANDO A MEDIÇÃO 'TRADES' DO AMBIENTE '{environment}' ---")

        # Get the base DB config (URL, token, org)
        db_config = config_manager.get_db_config()

        # Determine the correct bucket name based on the environment and add it to the config
        if environment == 'trade':
            bucket_key = 'bucket_live'
        elif environment == 'test':
            bucket_key = 'bucket_testnet'
        elif environment == 'backtest':
            bucket_key = 'bucket_backtest'
        
        bucket_name = config_manager.get('INFLUXDB', bucket_key)
        db_config['bucket'] = bucket_name
        
        db_manager = DatabaseManager(config=db_config)


        start = "1970-01-01T00:00:00Z"
        stop = pd.Timestamp.now(tz='UTC').isoformat()

        # PREDICADO DE EXCLUSÃO: Remove todos os pontos da medição 'trades' do bucket alvo.
        # A segurança é garantida pela seleção do bucket com base no argumento --env.
        # Isto corrige um bug onde dados antigos eram marcados com o ambiente errado.
        predicate = f'_measurement="trades"'

        logger.info(f"Limpando TODOS os dados da medição 'trades' do bucket '{db_config['bucket']}'...")
        db_manager._client.delete_api().delete(start, stop, predicate, bucket=db_config['bucket'], org=db_config['org'])
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
