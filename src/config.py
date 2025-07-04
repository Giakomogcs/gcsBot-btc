# src/config.py (VERSÃO FINAL E COMPLETA)

from dotenv import load_dotenv
import os
import sys
from src.logger import logger

# Carrega as variáveis do arquivo .env para o ambiente
load_dotenv()

def get_config_var(var_name, default_value=None):
    """
    Função auxiliar para ler uma variável de ambiente e limpá-la.
    """
    value = os.getenv(var_name, default_value)
    if isinstance(value, str):
        return value.strip().strip("'\"")
    return value

# --- MODO DE OPERAÇÃO ---
MODE = get_config_var("MODE", "optimize").lower()
FORCE_OFFLINE_MODE = get_config_var("FORCE_OFFLINE_MODE", "False").lower() == 'true'

# --- VALIDAÇÃO CRÍTICA DO MODO OFFLINE ---
if FORCE_OFFLINE_MODE and MODE in ['test', 'trade']:
    error_message = f"CONFIGURAÇÃO INVÁLIDA: O bot não pode rodar em modo '{MODE.upper()}' quando 'FORCE_OFFLINE_MODE' está 'True'."
    logger.error("="*80)
    logger.error(error_message)
    logger.error("Trading real ou em testnet requer uma conexão ativa com a internet.")
    logger.error("Por favor, ajuste seu arquivo .env e tente novamente.")
    logger.error("="*80)
    sys.exit(1)

# --- CONFIGURAÇÕES DA BINANCE ---
SYMBOL = get_config_var("SYMBOL", "BTCUSDT").upper()
USE_TESTNET = (MODE == 'test')

API_KEY = get_config_var("BINANCE_TESTNET_API_KEY") if USE_TESTNET else get_config_var("BINANCE_API_KEY")
API_SECRET = get_config_var("BINANCE_TESTNET_API_SECRET") if USE_TESTNET else get_config_var("BINANCE_API_SECRET")

if MODE in ['test', 'trade'] and not FORCE_OFFLINE_MODE and (not API_KEY or not API_SECRET):
    raise ValueError(f"Para MODE='{MODE}' em modo online, as chaves da API devem ser configuradas no .env")

# --- ESTRATÉGIA DE GESTÃO DE PORTFÓLIO E RISCO ---
MAX_USDT_ALLOCATION = float(get_config_var("MAX_USDT_ALLOCATION", 1000.0))
# Estes valores abaixo são apenas fallbacks. Os valores reais virão do 'strategy_params.json' otimizado.
RISK_PER_TRADE_PCT = float(get_config_var("RISK_PER_TRADE_PCT", 0.02))

# --- CONFIGURAÇÕES DE ARQUIVOS ---
DATA_DIR = "data"
LOGS_DIR = "logs"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

KAGGLE_BOOTSTRAP_FILE = os.path.join(DATA_DIR, "kaggle_btc_1m_bootstrap.csv")
HISTORICAL_DATA_FILE = os.path.join(DATA_DIR, f"full_historical_{SYMBOL}.csv")
COMBINED_DATA_CACHE_FILE = os.path.join(DATA_DIR, "combined_data_cache.csv")

MODEL_FILE = os.path.join(DATA_DIR, "trading_model.joblib") # Alterado para .joblib
SCALER_FILE = os.path.join(DATA_DIR, "scaler.joblib")     # Alterado para .joblib
TRADES_LOG_FILE = os.path.join(DATA_DIR, "trades_log.csv")
BOT_STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")
WFO_STATE_FILE = os.path.join(DATA_DIR, "wfo_optimization_state.json")
STRATEGY_PARAMS_FILE = os.path.join(DATA_DIR, "strategy_params.json")

# <<< PASSO 1: Adicionar o caminho para o arquivo de metadados >>>
MODEL_METADATA_FILE = os.path.join(DATA_DIR, "model_metadata.json")

# --- PARÂMETROS PARA A OTIMIZAÇÃO WALK-FORWARD ---
# <<< PASSO 2: Ajustar o período de treino para a estratégia "Generalista Sábio" >>>
# O valor ideal é entre 12 a 24 meses. Vamos usar 18 meses.
# 18 meses * 30 dias/mês * 24 horas/dia * 60 minutos/hora = 777,600 (aprox. 788400 com meses de 31 dias)
WFO_TRAIN_MINUTES = int(get_config_var("WFO_TRAIN_MINUTES", 788400)) # ~18 meses
# WFO_TRAIN_MINUTES = int(get_config_var("WFO_TRAIN_MINUTES", 43200)) # ~30 dias (Especialista Ágil)

WFO_TEST_MINUTES = int(get_config_var("WFO_TEST_MINUTES", 20160))  # ~14 dias
WFO_STEP_MINUTES = int(get_config_var("WFO_STEP_MINUTES", 20160))  # ~14 dias

# --- NOVOS PARÂMETROS PARA O MODO DE BACKTEST RÁPIDO ---
BACKTEST_START_DATE = get_config_var("BACKTEST_START_DATE", "2024-01-01")
BACKTEST_END_DATE = get_config_var("BACKTEST_END_DATE", "2025-03-31")

# <<< PASSO 3: Adicionar o parâmetro de validade do modelo >>>
MODEL_VALIDITY_MONTHS = int(get_config_var("MODEL_VALIDITY_MONTHS", 3)) # O modelo será considerado válido por 3 meses