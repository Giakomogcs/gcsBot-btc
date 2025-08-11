# scripts/db_utils.py (CORRECTED WITH TIMEOUT)
import sys
from datetime import datetime, timezone
import os
import argparse
from typing import Optional

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from influxdb_client import InfluxDBClient

def delete_measurement(measurement_name: str, environment: Optional[str] = None):
    """Deleta todos os dados de uma 'measurement' (tabela) específica no InfluxDB."""

    log_message = f"--- 🚮 INICIANDO EXCLUSÃO DA TABELA (MEASUREMENT): {measurement_name}"
    if environment:
        log_message += f" NO AMBIENTE: {environment.upper()}"
    log_message += " 🚮 ---"
    logger.info(log_message)
    
    try:
        db_config = config_manager.get_section('INFLUXDB')
        if environment == 'test':
            db_config['bucket'] = 'jules_bot_test_v1'
        elif environment == 'backtest':
            db_config['bucket'] = 'jules_bot_backtest_v1'

        client = InfluxDBClient(
            url=db_config['url'],
            token=db_config['token'],
            org=db_config['org'],
            timeout=300_000 
        )
        
        delete_api = client.delete_api()
        
        start = "1970-01-01T00:00:00Z"
        stop = datetime.now(timezone.utc).isoformat()
        bucket = db_config['bucket']
        org = db_config['org']
        
        predicate = f'_measurement="{measurement_name}"'
        if measurement_name == "trades" and environment:
            predicate += f' AND environment="{environment}"'

        logger.info(f"Executando exclusão com o predicado: {predicate}")
        delete_api.delete(start, stop, predicate, bucket, org)
        
        logger.info(f"✅ Solicitação de exclusão para '{measurement_name}' (ambiente: {environment or 'todos'}) enviada com sucesso.")
        client.close()
        
    except Exception as e:
        logger.error(f"❌ Falha ao tentar excluir a measurement '{measurement_name}': {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deleta uma measurement do InfluxDB, com verificação de ambiente para 'trades'.")
    parser.add_argument("measurement", help="O nome da measurement a ser deletada.")
    parser.add_argument(
        '--env',
        type=str,
        choices=['trade', 'test', 'backtest'],
        help="O ambiente de execução a ser limpo (obrigatório se a measurement for 'trades')."
    )
    args = parser.parse_args()

    if args.measurement == "trades" and not args.env:
        logger.error("Para a measurement 'trades', o argumento --env é obrigatório por segurança.")
        logger.error("Uso: python scripts/db_utils.py trades --env <trade|test|backtest>")
        sys.exit(1)

    delete_measurement(args.measurement, args.env)