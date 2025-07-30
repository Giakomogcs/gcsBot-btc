# src/config_manager.py (VERSÃO FINAL E CORRETA)

import yaml
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import BaseModel


class InfluxDBConfig(BaseModel):
    url: str
    token: str
    org: str
    bucket: str

class DatabaseConfig(BaseModel):
    influxdb: InfluxDBConfig

class BacktestConfig(BaseModel):
    start_date: str
    initial_capital: float
    commission_rate: float

class TripleBarrierConfig(BaseModel):
    profit_mult: float
    stop_mult: float
    time_limit_candles: int

class SpecialistConfig(BaseModel):
    filename: str
    features: list[str]

class ModelsConfig(BaseModel):
    models_path: str
    specialists: dict[str, SpecialistConfig]

class TradingStrategyConfig(BaseModel):
    confidence_threshold: float
    triple_barrier: TripleBarrierConfig
    models: ModelsConfig
    ensemble_weights: dict[str, float]

class PositionSizingConfig(BaseModel):
    method: str
    risk_per_trade: float

class OptimizerConfig(BaseModel):
    n_trials: int
    storage_name: str
    objective_metric: str

class LoggingConfig(BaseModel):
    level: str

# --- A Classe Principal de Configurações ---
# Ela herda de BaseModel, pois vamos popular os dados manualmente.

class Settings(BaseModel):
    database: DatabaseConfig
    backtest: BacktestConfig
    trading_strategy: TradingStrategyConfig
    position_sizing: PositionSizingConfig
    optimizer: OptimizerConfig
    logging: LoggingConfig

# --- A LÓGICA DE CARREGAMENTO (SIMPLES E DIRETA) ---

def load_settings() -> Settings:
    """
    Carrega as configurações do arquivo config.yml e as valida com Pydantic.
    Esta é a abordagem mais robusta e simples.
    """
    config_path = Path('config.yml')
    if not config_path.is_file():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado em: {config_path.resolve()}")

    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)

    return Settings(**config_data)

# --- A INSTÂNCIA FINAL ---
# Chamamos nossa função para criar a instância única de configurações.
settings = load_settings()