# main.py (VERSÃO 2.0 - CORRIGIDO E ALINHADO COM A ARQUITETURA V8)

import sys
import os
import pandas as pd
from src.config_manager import settings
from src.logger import logger

def main():
    """
    Ponto de entrada principal do bot.
    Lê o modo de operação e inicia o processo correspondente.
    """
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    if settings.MODE == 'optimize':
        logger.info("--- MODO: OTIMIZAÇÃO WALK-FORWARD ---")
        logger.info("Iniciando o processo de otimização para encontrar os melhores parâmetros...")

        from src.data_manager import DataManager
        from src.core.optimizer import WalkForwardOptimizer

        # O DataManager é responsável por carregar, processar e fazer o cache dos dados
        dm = DataManager()
        # Garante que temos os dados mais recentes e todas as features calculadas
        full_historical_data = dm.update_and_load_data(settings.SYMBOL, '1m')

        if full_historical_data.empty:
            logger.error("Não foram encontrados dados históricos para a otimização. Verifique a conexão ou os arquivos locais. Abortando.")
            sys.exit(1)

        # A "Fábrica de Especialistas" é instanciada com os dados e a lista de features
        optimizer = WalkForwardOptimizer(full_historical_data, dm.feature_names)
        # O método run() inicia todo o processo de otimização, que pode levar horas
        optimizer.run()

    elif settings.MODE == 'backtest':
        logger.info(f"--- MODO: BACKTEST RÁPIDO ---")
        from src.core.quick_tester import QuickTester
        
        tester = QuickTester()
        tester.run(start_date_str=settings.BACKTEST_START_DATE, end_date_str=settings.BACKTEST_END_DATE)

    elif settings.MODE in ['test', 'trade']:
        logger.info(f"--- MODO: {settings.MODE.upper()} ---")
        
        if settings.MODE == 'test':
            logger.info("************************************************************")
            logger.info(">>> OPERANDO NA BINANCE TESTNET (CARTEIRA DE TESTE) <<<")
            logger.info("************************************************************")
        else:
            logger.warning("************************************************************")
            logger.warning(">>> ATENÇÃO: OPERANDO NA BINANCE REAL (CARTEIRA REAL) <<<")
            logger.warning("************************************************************")

        from src.core.trading_bot import TradingBot
        
        bot = TradingBot()
        bot.run()

    else:
        logger.error(f"Modo '{settings.MODE}' não reconhecido no .env. Use 'optimize', 'test', ou 'trade'.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nExecução interrompida pelo usuário.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Um erro crítico encerrou a aplicação: {e}", exc_info=True)
        sys.exit(1)