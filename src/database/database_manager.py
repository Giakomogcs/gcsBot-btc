# src/database/database_manager.py

import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, TypedDict

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# Configuração do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Usamos TypedDict para definir um "schema" claro para nossos trades.
# Isso ajuda a evitar erros e torna a integração entre os módulos mais segura.
class Trade(TypedDict):
    trade_id: str
    status: str  # 'OPEN', 'CLOSED_PROFIT', 'CLOSED_LOSS', 'CLOSED_BREAKEVEN'
    entry_price: float
    quantity: float
    entry_time: datetime
    entry_reason: str # 'first_entry', 'dca_level_1', etc.
    stop_loss_price: float
    profit_target_price: float
    # Campos que são preenchidos no fechamento
    exit_price: Optional[float]
    exit_time: Optional[datetime]
    exit_reason: Optional[str] # 'target_hit', 'stop_loss_hit', etc.
    pnl_usd: Optional[float]
    pnl_percentage: Optional[float]


class DatabaseManager:
    """
    Gerencia toda a comunicação com o banco de dados InfluxDB.
    Esta versão é orientada ao conceito de "Trade Soberano", onde cada trade
    é uma entidade única e rastreável.
    """
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        # O measurement (tabela) para a nova estrutura de portfólio.
        self.measurement_name = "trades_portfolio"
        try:
            self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.query_api = self.client.query_api()
            # Verifica a conexão
            if not self.client.ping():
                 raise ConnectionError("Não foi possível conectar ao InfluxDB.")
            logging.info("Conexão com InfluxDB estabelecida com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao inicializar o DatabaseManager: {e}")
            raise

    def save_new_trade(self, trade_data: Dict[str, Any]) -> Optional[str]:
        """
        Salva um novo trade no banco de dados com status 'OPEN'.
        Gera um ID de trade único.

        Args:
            trade_data (Dict[str, Any]): Um dicionário contendo os dados do trade
                                         (entry_price, quantity, entry_time, etc.).

        Returns:
            Optional[str]: O ID do trade recém-criado, ou None se falhar.
        """
        trade_id = str(uuid.uuid4())
        point = (
            Point(self.measurement_name)
            .tag("trade_id", trade_id)
            .tag("status", "OPEN") # O status inicial é sempre OPEN
            .field("entry_price", float(trade_data["entry_price"]))
            .field("quantity", float(trade_data["quantity"]))
            .field("entry_reason", str(trade_data["entry_reason"]))
            .field("stop_loss_price", float(trade_data["stop_loss_price"]))
            .field("profit_target_price", float(trade_data["profit_target_price"]))
            .time(trade_data["entry_time"])
        )

        try:
            self.write_api.write(bucket=self.bucket, record=point)
            logging.info(f"Novo trade salvo com sucesso. ID: {trade_id}")
            return trade_id
        except Exception as e:
            logging.error(f"Falha ao salvar novo trade no InfluxDB: {e}")
            return None

    def update_closed_trade(self, closed_trade_data: Trade) -> bool:
        """
        Atualiza um trade existente para o status de fechado, adicionando
        informações de saída. Em InfluxDB, "atualizar" significa reescrever
        o ponto com os novos campos.

        Args:
            closed_trade_data (Trade): O objeto completo do trade com todos os
                                       dados de fechamento preenchidos.

        Returns:
            bool: True se a atualização for bem-sucedida, False caso contrário.
        """
        if "trade_id" not in closed_trade_data or "status" not in closed_trade_data:
            logging.error("Dados de trade fechado inválidos. Faltando 'trade_id' ou 'status'.")
            return False

        point = (
            Point(self.measurement_name)
            .tag("trade_id", closed_trade_data["trade_id"])
            .tag("status", closed_trade_data["status"]) # Novo status: CLOSED_PROFIT, etc.
            .field("entry_price", float(closed_trade_data["entry_price"]))
            .field("quantity", float(closed_trade_data["quantity"]))
            .field("entry_reason", str(closed_trade_data["entry_reason"]))
            .field("stop_loss_price", float(closed_trade_data["stop_loss_price"]))
            .field("profit_target_price", float(closed_trade_data["profit_target_price"]))
            .field("exit_price", float(closed_trade_data["exit_price"]))
            .field("exit_reason", str(closed_trade_data["exit_reason"]))
            .field("pnl_usd", float(closed_trade_data["pnl_usd"]))
            .field("pnl_percentage", float(closed_trade_data["pnl_percentage"]))
            # Usamos o tempo de fechamento para a atualização
            .time(closed_trade_data["exit_time"])
        )

        try:
            self.write_api.write(bucket=self.bucket, record=point)
            logging.info(f"Trade ID {closed_trade_data['trade_id']} atualizado para status {closed_trade_data['status']}.")
            return True
        except Exception as e:
            logging.error(f"Falha ao atualizar trade {closed_trade_data['trade_id']} no InfluxDB: {e}")
            return False

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """
        Busca todos os trades que estão atualmente com o status 'OPEN'.
        Essencial para o PositionManager verificar a cada vela.

        Returns:
            List[Dict[str, Any]]: Uma lista de dicionários, cada um representando um trade aberto.
        """
        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: -365d) // Busca em um range amplo o suficiente
          |> filter(fn: (r) => r._measurement == "{self.measurement_name}")
          |> filter(fn: (r) => r.status == "OPEN")
          |> last() // Pega o estado mais recente de cada trade
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        try:
            tables = self.query_api.query(query, org=self.org)
            results = [record.values for table in tables for record in table.records]
            return results
        except Exception as e:
            logging.error(f"Falha ao buscar trades abertos: {e}")
            return []

    def get_all_closed_trades(self) -> List[Dict[str, Any]]:
        """
        Busca todos os trades fechados para fins de análise e relatórios.

        Returns:
            List[Dict[str, Any]]: Uma lista de dicionários com todos os trades fechados.
        """
        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: -365d)
          |> filter(fn: (r) => r._measurement == "{self.measurement_name}")
          |> filter(fn: (r) => r.status != "OPEN")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        try:
            tables = self.query_api.query(query, org=self.org)
            results = [record.values for table in tables for record in table.records]
            return results
        except Exception as e:
            logging.error(f"Falha ao buscar trades fechados: {e}")
            return []

    def close(self):
        """Fecha o cliente do InfluxDB."""
        self.client.close()
        logging.info("Conexão com InfluxDB fechada.")