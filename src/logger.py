# src/logger.py (VERSÃO 4.3 - Preparado para Dashboard)

import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import os
from tabulate import tabulate
import pandas as pd

try:
    from src.config import MODE, LOGS_DIR
except ImportError:
    MODE = os.getenv("MODE", "optimize").lower()
    LOGS_DIR = "logs"

os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger("gcsBot")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # Handler para Arquivo (Log Completo, sem alterações)
    log_file_path = os.path.join(LOGS_DIR, 'gcs_bot.log')
    file_handler = TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=14, encoding='utf-8'
    )
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # <<< MUDANÇA: O HANDLER DO CONSOLE AGORA É MAIS SELETIVO >>>
    # Evita que logs de INFO poluam a tela do dashboard.
    # Apenas avisos e erros importantes serão exibidos sobre o painel.
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.WARNING) # Só exibe WARNING, ERROR, CRITICAL
    logger.addHandler(console_handler)

    logger.info(f"Logger configurado para o modo: '{MODE.upper()}'. Logs de console a partir do nível WARNING.")

def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    # Esta função continua a mesma, mas será chamada pelo novo DisplayManager
    try:
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
        # O log da tabela agora será apenas para o ARQUIVO, não para o console.
        # A exibição no console será controlada pelo DisplayManager.
        logging.getLogger("gcsBot").info(f"\n--- {title} ---\n{table}")
    except Exception as e:
        logging.getLogger("gcsBot").error(f"Erro ao gerar a tabela '{title}': {e}")