# scripts/db_utils.py (CORRECTED WITH TIMEOUT)
import sys
from datetime import datetime, timezone
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config_manager import settings
from src.logger import logger
from influxdb_client import InfluxDBClient

def delete_measurement(measurement_name: str):
    """Deleta todos os dados de uma 'measurement' (tabela) específica no InfluxDB."""
    logger.info(f"--- 🚮 INICIANDO EXCLUSÃO DA TABELA (MEASUREMENT): {measurement_name} 🚮 ---")
    
    try:
        # --- INÍCIO DA CORREÇÃO ---
        # Aumentamos o timeout para 5 minutos (300,000 ms) para dar tempo ao DB
        client = InfluxDBClient(
            url=settings.database.url,
            token=settings.database.token,
            org=settings.database.org,
            timeout=300_000 
        )
        # --- FIM DA CORREÇÃO ---
        
        delete_api = client.delete_api()
        
        start = "1970-01-01T00:00:00Z"
        stop = datetime.now(timezone.utc).isoformat()
        bucket = settings.database.bucket
        org = settings.database.org
        
        delete_api.delete(start, stop, f'_measurement="{measurement_name}"', bucket, org)
        
        logger.info(f"✅ Solicitação de exclusão para '{measurement_name}' enviada com sucesso.")
        client.close()
        
    except Exception as e:
        logger.error(f"❌ Falha ao tentar excluir a measurement '{measurement_name}': {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        measurement_to_delete = sys.argv[1]
        delete_measurement(measurement_to_delete)
    else:
        logger.error("Nenhum nome de measurement fornecido. Uso: python scripts/db_utils.py <nome_da_tabela>")
        sys.exit(1)