# src/logger.py (VERSÃO 4.1 - COM UTILITÁRIO log_table CENTRALIZADO)

import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import os
from tabulate import tabulate

# Configuração do Logger
try:
    from src.config import MODE, LOGS_DIR
except ImportError:
    # Fallback para caso este módulo seja importado antes do config
    MODE = os.getenv("MODE", "optimize").lower()
    LOGS_DIR = "logs"

os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger("gcsBot")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # --- Handler para Arquivo (Log Completo) ---
    log_file_path = os.path.join(LOGS_DIR, 'gcs_bot.log')
    file_handler = TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=14, encoding='utf-8'
    )
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # --- Handler para Console (Log Inteligente) ---
    console_handler = logging.StreamHandler(sys.stdout)
    if MODE == 'optimize':
        # Console limpo para otimização, mostrando apenas mensagens de alto nível
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setLevel(logging.INFO)
    else:
        # Console detalhado para trading e backtesting
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setLevel(logging.INFO)

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logger.info(f"Logger configurado para o modo: '{MODE.upper()}'")

### PASSO 1: Centralizar a função 'log_table' aqui ###
def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    """
    Formata dados em uma tabela bonita e a envia para o logger principal.
    
    Args:
        title (str): O título a ser exibido acima da tabela.
        data (list of lists or list of dicts): Os dados a serem tabulados.
        headers (any): O tipo de cabeçalho a ser usado pelo tabulate.
        tablefmt (str): O formato da tabela (ex: 'heavy_grid', 'pipe').
    """
    try:
        # Garante que os dados não estejam vazios para evitar erro no tabulate
        if not data:
            logger.info(f"\n--- {title} ---\n(Sem dados para exibir)")
            return
            
        table = tabulate(data, headers=headers, tablefmt=tablefmt, stralign="right")
        logger.info(f"\n--- {title} ---\n{table}")
    except Exception as e:
        logger.error(f"Erro ao gerar a tabela '{title}': {e}")