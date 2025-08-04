# src/config_manager.py (VERSÃO CORRIGIDA E COMPLETA)

import yaml
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Modelos para o .env ---
# Esta seção está correta. O Pydantic irá ler o .env e popular estes modelos.
class InfluxDBConfig(BaseSettings):
    # Procura por um ficheiro .env e carrega as variáveis
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    
    url: str = Field(..., alias='INFLUXDB_URL')
    token: str = Field(..., alias='INFLUXDB_TOKEN')
    org: str = Field(..., alias='INFLUXDB_ORG')
    bucket: str = Field(..., alias='INFLUXDB_BUCKET')

class ApiKeysConfig(BaseSettings):
    # Procura por um ficheiro .env e carrega as variáveis
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    
    binance_api_key: str = Field("", alias='BINANCE_API_KEY')
    binance_api_secret: str = Field("", alias='BINANCE_API_SECRET')
    binance_testnet_api_key: str = Field("", alias='BINANCE_TESTNET_API_KEY')
    binance_testnet_api_secret: str = Field("", alias='BINANCE_TESTNET_API_SECRET')


# --- Modelos para o config.yml ---
# Toda esta seção está perfeita e não precisa de alterações.
class AppConfig(BaseModel):
    use_testnet: bool
    force_offline_mode: bool
    symbol: str

class DataPathsConfig(BaseModel):
    macro_data_dir: str
    historical_data_file: str
    kaggle_bootstrap_file: str
    models_dir: str

class TargetConfig(BaseModel):
    future_periods: int
    profit_mult: float
    stop_mult: float

class DataPipelineConfig(BaseModel):
    start_date_ingestion: str
    regime_features: list[str]
    tags_for_master_table: list[str]
    target: TargetConfig

class SpecialistConfig(BaseModel):
    features: list[str]

class ModelsConfig(BaseModel):
    specialists: dict[str, SpecialistConfig]

class TripleBarrierConfig(BaseModel):
    profit_mult: float
    stop_mult: float
    time_limit_candles: int

class TradingStrategyConfig(BaseModel):
    static_confidence_threshold: float
    first_entry_confidence_factor: float
    dca_grid_spacing_percent: float
    triple_barrier: TripleBarrierConfig
    models: ModelsConfig
    ensemble_weights: dict[str, float]

class PositionSizingConfig(BaseModel):
    method: str
    risk_per_trade: float

class OptimizerConfig(BaseModel):
    n_trials: int
    quality_threshold: float
    objective_metric: str

class LoggingConfig(BaseModel):
    level: str

class BacktestConfig(BaseModel):
    start_date: str
    initial_capital: int
    commission_rate: float

class PositionManagementConfig(BaseModel):
    profit_target_percent: float
    max_concurrent_trades: int
    capital_per_trade_percent: float

class DynamicSizingConfig(BaseModel):
    enabled: bool
    performance_window_trades: int
    profit_factor_threshold: float
    performance_upscale_factor: float
    performance_downscale_factor: float


# --- Classe de Configuração Principal (COM A CORREÇÃO) ---
class Settings(BaseModel):
    """
    Combina as configurações do .env e do config.yml de forma explícita.
    """
    # 1. Estas configurações serão preenchidas PRIMEIRO a partir do .env
    #    graças aos modelos BaseSettings que definimos acima.
    database: InfluxDBConfig = InfluxDBConfig()
    api_keys: ApiKeysConfig = ApiKeysConfig()
    
    # 2. Estas configurações serão preenchidas a partir do config.yml
    app: AppConfig
    data_paths: DataPathsConfig
    data_pipeline: DataPipelineConfig
    trading_strategy: TradingStrategyConfig
    position_sizing: PositionSizingConfig
    optimizer: OptimizerConfig
    logging: LoggingConfig
    backtest: BacktestConfig
    position_management: PositionManagementConfig
    dynamic_sizing: DynamicSizingConfig


def load_settings() -> Settings:
    """
    Carrega o ficheiro YAML e o utiliza para criar a instância final de Settings.
    """
    try:
        with open('config.yml', 'r') as f:
            yaml_data = yaml.safe_load(f)
            # O Pydantic irá inteligentemente mapear o dicionário do YAML
            # para os modelos correspondentes dentro da classe Settings.
            return Settings(**yaml_data)
    except FileNotFoundError:
        print("Erro: O ficheiro 'config.yml' não foi encontrado.")
        raise
    except Exception as e:
        print(f"Erro ao carregar as configurações: {e}")
        raise

# Carrega as configurações uma vez para toda a aplicação
settings = load_settings()