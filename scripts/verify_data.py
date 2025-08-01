# Ficheiro: scripts/verify_data.py

import os
import sys
from dateutil.relativedelta import relativedelta
import pandas as pd

# Resolução de Path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.database_manager import db_manager
from src.logger import logger
from src.config_manager import settings

def check_measurement_data(measurement: str, start_date: str, end_date: str):
    """Verifica a contagem de registros em uma medição para um determinado período."""
    logger.info(f"Verificando dados para '{measurement}' de {start_date} a {end_date}...")
    query_api = db_manager.get_query_api()
    if not query_api:
        logger.error("API de consulta do InfluxDB indisponível.")
        return False

    # Query para contar registros de forma eficiente
    query = f'''
        from(bucket: "{settings.database.bucket}")
            |> range(start: {start_date}, stop: {end_date})
            |> filter(fn: (r) => r._measurement == "{measurement}")
            |> filter(fn: (r) => r._field == "close") 
            |> count()
    '''
    try:
        result = query_api.query(query)
        count = result[0].records[0].get_value() if result and result[0].records else 0
        
        # Um mês de dados de 1 minuto tem aproximadamente 43200 pontos.
        # Um período de 2 meses com warmup deve ter mais de 80.000.
        logger.info(f"RESULTADO: {count} pontos de dados ('close') encontrados para '{measurement}'.")
        if count < 40000: # Usamos um limiar baixo para detectar o problema
            logger.error("ALERTA CRÍTICO: A quantidade de dados é extremamente baixa. A ingestão de dados históricos para este período falhou ou não foi executada.")
            return False
        else:
            logger.info("✅ Verificação de dados bem-sucedida. Quantidade de dados parece saudável.")
            return True
            
    except Exception as e:
        logger.error(f"Erro ao consultar o InfluxDB: {e}")
        return False

if __name__ == '__main__':
    # Verifique o período exato que está a falhar
    logger.info("--- INICIANDO VERIFICAÇÃO DE DADOS NO BANCO ---")
    check_measurement_data(
        measurement="btc_btcusdt_1m",
        start_date="2017-11-27T00:00:00Z", # Inclui warmup para Jan 2018
        end_date="2018-02-01T00:00:00Z"
    )
