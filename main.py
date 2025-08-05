# Ficheiro: main.py (VERSÃO COM IA)

import time
from datetime import datetime
import pandas as pd
import os

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.core.position_manager import PositionManager
from gcs_bot.core.exchange_manager import exchange_manager
from gcs_bot.core.account_manager import AccountManager
from gcs_bot.database.database_manager import db_manager
# --- NOVA IMPORTAÇÃO ---
from gcs_bot.core.predictor import Predictor

def main_loop():
    """O loop principal que executa a cada minuto."""
    logger.info("🚀 --- INICIANDO O LOOP PRINCIPAL DO BOT DE TRADING (MODO IA) --- 🚀")
    
    # --- INÍCIO DA NOVA LÓGICA DE INICIALIZAÇÃO ---
    # Encontra o modelo treinado mais recente na pasta de modelos
    model_dir = Path(settings.data_paths.models_dir)
    latest_model_path = max([str(f) for f in model_dir.glob('*.joblib')], key=os.path.getctime, default=None)

    if not latest_model_path:
        logger.critical("NENHUM MODELO TREINADO ENCONTRADO. O BOT NÃO PODE OPERAR.")
        logger.critical("Execute o otimizador com './manage.ps1 optimize' primeiro.")
        return

    # Inicializa os nossos gestores
    predictor = Predictor(model_path=latest_model_path)
    account_manager = AccountManager(binance_client=exchange_manager.client)
    position_manager = PositionManager(
        config=settings,
        db_manager=db_manager,
        logger=logger,
        account_manager=account_manager
    )
    # --- FIM DA NOVA LÓGICA DE INICIALIZAÇÃO ---

    while True:
        try:
            logger.info("--- Novo ciclo de verificação ---")
            
            current_price = exchange_manager.get_current_price(settings.app.symbol)
            if current_price is None:
                logger.error("Não foi possível obter o preço atual. A saltar este ciclo.")
                time.sleep(60)
                continue

            current_candle = pd.Series({'close': current_price, 'timestamp': datetime.now()})
            logger.info(f"Preço atual de {settings.app.symbol}: ${current_price:,.2f}")

            # Sempre verificar saídas primeiro
            closed_trades = position_manager.check_and_close_positions(current_candle)
            if closed_trades:
                for trade in closed_trades:
                    logger.info(f"✅ POSIÇÃO FECHADA: P&L de ${trade['pnl_usdt']:.2f} realizado.")

            # --- LÓGICA DE SINAL SUBSTITUÍDA ---
            # O predictor agora gera o sinal usando o modelo de IA
            signal = predictor.generate_signal()
            
            if signal == "BUY":
                position_manager.check_for_entry(signal, current_price)
            else:
                logger.info("Sinal NEUTRAL. Nenhuma nova posição será aberta.")
            
            logger.info("--- Ciclo concluído. A aguardar 60 segundos... ---")
            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("🛑 Interrupção manual detectada. A desligar o bot...")
            break
        except Exception as e:
            logger.critical(f"❌ Ocorreu um erro crítico no loop principal: {e}", exc_info=True)
            logger.info("A aguardar 5 minutos antes de reiniciar o loop para evitar spam de erros.")
            time.sleep(300)

if __name__ == '__main__':
    from pathlib import Path # Importação adicional para o bloco main
    main_loop()