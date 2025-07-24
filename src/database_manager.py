# src/database_manager.py

from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from src.config_manager import settings
from src.logger import logger # Assumindo que você tem um logger configurado

class DatabaseManager:
    """
    Gerencia todas as interações com o banco de dados InfluxDB.
    """
    def __init__(self):
        self.url = settings.influxdb_url
        self.token = settings.influxdb_token
        self.org = settings.influxdb_org
        self._client = None
        self.connect()

    def connect(self):
        """Estabelece a conexão com o InfluxDB."""
        try:
            self._client = InfluxDBClient(url=self.url, token=self.token, org=self.org, timeout=300_000)
            # Verifica a conexão
            if self._client.health().status == "pass":
                logger.info("✅ Conexão com InfluxDB estabelecida com sucesso!")
            else:
                logger.error("❌ Falha ao conectar com InfluxDB. Verifique a saúde do serviço.")
                self._client = None
        except Exception as e:
            logger.error(f"❌ Erro crítico ao conectar com InfluxDB: {e}", exc_info=True)
            self._client = None

    def get_write_api(self):
        """Retorna a API de escrita para inserir dados."""
        if not self._client:
            logger.warning("Não há conexão com o InfluxDB. Tentando reconectar...")
            self.connect()
            if not self._client:
                return None
        return self._client.write_api(write_options=SYNCHRONOUS)

    def get_query_api(self):
        """Retorna a API de consulta para buscar dados."""
        if not self._client:
            logger.warning("Não há conexão com o InfluxDB. Tentando reconectar...")
            self.connect()
            if not self._client:
                return None
        return self._client.query_api()

    def close(self):
        """Fecha a conexão com o banco de dados."""
        if self._client:
            self._client.close()
            logger.info("Conexão com InfluxDB fechada.")
            

# Instância única para ser usada em outros módulos
db_manager = DatabaseManager()