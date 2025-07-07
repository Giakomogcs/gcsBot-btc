# src/logger.py (VERSÃO 4.2 - CORRIGIDO)

import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import os
from tabulate import tabulate
import pandas as pd

# Configuração do Logger
try:
    from src.config import MODE, LOGS_DIR
except ImportError:
    MODE = os.getenv("MODE", "optimize").lower()
    LOGS_DIR = "logs"

os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger("gcsBot")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # Handler para Arquivo (Log Completo)
    log_file_path = os.path.join(LOGS_DIR, 'gcs_bot.log')
    file_handler = TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=14, encoding='utf-8'
    )
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # Handler para Console (Log Inteligente)
    console_handler = logging.StreamHandler(sys.stdout)
    if MODE == 'optimize':
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setLevel(logging.INFO)
    else:
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setLevel(logging.INFO)

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logger.info(f"Logger configurado para o modo: '{MODE.upper()}'")


def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    """
    Formata dados em uma tabela bonita e a envia para o logger principal.
    """
    try:
        # CORREÇÃO: Usar 'data.empty' para verificar DataFrames do Pandas
        is_empty = False
        if isinstance(data, pd.DataFrame):
            is_empty = data.empty
        elif isinstance(data, list):
            is_empty = not data
        elif data is None:
            is_empty = True

        if is_empty:
            logger.info(f"\n--- {title} ---\n(Sem dados para exibir)")
            return
            
        table = tabulate(data, headers=headers, tablefmt=tablefmt, stralign="right")
        logger.info(f"\n--- {title} ---\n{table}")
    except Exception as e:
        logger.error(f"Erro ao gerar a tabela '{title}': {e}")
