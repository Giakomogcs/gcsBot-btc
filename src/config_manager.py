# Ficheiro: src/config_manager.py (VERSÃO FINAL E ROBUSTA)

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any
from src.logger import logger

# --- Modelos para o .env (Segredos) ---
class InfluxDBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    url: str = Field(..., alias='INFLUXDB_URL')
    token: str = Field(..., alias='INFLUXDB_TOKEN')
    org: str = Field(..., alias='INFLUXDB_ORG')
    bucket: str = Field(..., alias='INFLUXDB_BUCKET')

class ApiKeysConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    binance_api_key: str = Field("", alias='BINANCE_API_KEY')
    binance_api_secret: str = Field("", alias='BINANCE_API_SECRET')
    binance_testnet_api_key: str = Field("", alias='BINANCE_TESTNET_API_KEY')
    binance_testnet_api_secret: str = Field("", alias='BINANCE_TESTNET_API_SECRET')

# --- Modelos para o config.yml (Estratégia e Parâmetros) ---
class BacktestConfig(BaseModel):
    start_date: str
    initial_capital: int
    commission_rate: float
    # --- NOVOS PARÂMETROS ESTRATÉGICOS ---
    first_entry_confidence_factor: float = 0.80
    buy_the_dip_trigger_percent: float = -2.0

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
    confidence_threshold: float
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

# --- Classe de Configuração Principal (com carregamento explícito) ---
class Settings(BaseModel):
    # Campos que vêm do .env
    database: InfluxDBConfig
    api_keys: ApiKeysConfig
    
    # Campos que vêm do config.yml
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
    Carrega as configurações de forma robusta e explícita.
    Primeiro, carrega os segredos do .env.
    Depois, carrega a estratégia do config.yml.
    Finalmente, combina e valida tudo com Pydantic.
    """
    try:
        # Carrega a configuração do ficheiro YAML
        with open('config.yml', 'r') as f:
            yaml_data = yaml.safe_load(f)

        # Carrega os segredos do .env usando os modelos Pydantic
        env_data = {
            'database': InfluxDBConfig().model_dump(),
            'api_keys': ApiKeysConfig().model_dump()
        }
        
        # Combina os dois dicionários
        full_config_data = {**yaml_data, **env_data}
        
        # Valida a configuração completa
        settings_object = Settings(**full_config_data)
        logger.info("✅ Configurações carregadas e validadas com sucesso.")
        return settings_object
        
    except FileNotFoundError:
        logger.error("Erro Crítico: O ficheiro 'config.yml' não foi encontrado.")
        raise
    except Exception as e:
        logger.error(f"Erro Crítico ao carregar as configurações: {e}")
        raise

# Instância única para toda a aplicação
settings = load_settings()