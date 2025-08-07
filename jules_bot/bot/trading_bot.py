import time
import pandas as pd
import json
import os
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import settings
from jules_bot.bot.position_manager import PositionManager
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.bot.account_manager import AccountManager
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.database.data_manager import DataManager

# --- Classes de Simulação para Backtesting ---

class SimulatedAccountManager:
    """
    Simula uma conta de exchange para o backtest, controlando o saldo.
    """
    def __init__(self, initial_balance_usdt=10000.0):
        self.usdt_balance = initial_balance_usdt
        self.btc_balance = 0.0
        logger.info(f"[SIMULADOR] Conta de backtest inicializada com ${self.usdt_balance:,.2f} USDT.")

    def update_on_buy(self, quote_order_qty):
        """Simula uma ordem de compra."""
        if self.usdt_balance < quote_order_qty:
            logger.warning(f"[SIMULADOR] Fundos insuficientes para comprar ${quote_order_qty:,.2f}.")
            return False
        # A quantidade de BTC comprada será calculada e adicionada pelo chamador.
        # Esta função apenas deduz o custo em USDT.
        self.usdt_balance -= quote_order_qty
        logger.info(f"[SIMULADOR] ORDEM DE COMPRA: ${quote_order_qty:,.2f}. Saldo USDT: ${self.usdt_balance:,.2f}")
        return True

    def update_on_sell(self, quantity_btc, current_price):
        """Simula uma ordem de venda."""
        if self.btc_balance < quantity_btc:
            logger.warning(f"[SIMULADOR] BTC insuficiente para vender {quantity_btc:.8f}.")
            return False
        self.btc_balance -= quantity_btc
        self.usdt_balance += quantity_btc * current_price
        logger.info(f"[SIMULADOR] ORDEM DE VENDA: {quantity_btc:.8f} BTC a ${current_price:,.2f}. Saldo USDT: ${self.usdt_balance:,.2f}")
        return True

class MockExchangeManager:
    """
    Um gestor de exchange falso para o PositionManager não falhar durante a inicialização no backtest.
    """
    def get_current_price(self, symbol):
        # Retorna 0.0 porque o preço real virá do loop de dados históricos.
        return 0.0

# --- Classe Principal do Bot ---

class TradingBot:
    """
    O maestro que orquestra todos os componentes do bot.
    Agora com lógicas separadas para live/test e backtest.
    """

    def __init__(self, mode: str):
        self.is_running = False
        self.mode = mode.lower()
        logger.info(f"--- INICIALIZANDO O TRADING BOT EM MODO '{self.mode.upper()}' ---")

        # --- ETAPA 1: Construção dos Managers ---
        logger.info("Construindo e injetando dependências...")
        self.db_manager = DatabaseManager(execution_mode=self.mode)
        self.data_manager = DataManager(db_manager=self.db_manager, config=settings, logger=logger)
        self.symbol = settings.app.symbol

        # --- Lógica de Inicialização por Modo ---
        if self.mode in ['trade', 'test']:
            self.exchange_manager = ExchangeManager(mode=self.mode)
            self.account_manager = AccountManager(binance_client=self.exchange_manager._client)
            self.position_manager = PositionManager(
                db_manager=self.db_manager,
                account_manager=self.account_manager,
                exchange_manager=self.exchange_manager
            )
            self.position_manager.reconcile_states()
        else: # MODO BACKTEST
            logger.info("Modo Backtest: A usar gestores simulados.")
            self.exchange_manager = None
            # CORREÇÃO: Usando o nome correto do atributo do config.yml
            initial_balance = settings.backtest.initial_capital
            self.account_manager = SimulatedAccountManager(initial_balance_usdt=initial_balance)
            # Usa um mock para o exchange_manager para que o PositionManager possa ser inicializado
            mock_exchange_manager = MockExchangeManager()
            self.position_manager = PositionManager(
                db_manager=self.db_manager,
                account_manager=self.account_manager,
                exchange_manager=mock_exchange_manager
            )
            logger.info("Modo Backtest: Conexão com a exchange ignorada.")

        logger.info("✅ Bot inicializado com sucesso.")

    def run(self):
        """
        O loop principal para TRADING e TEST.
        """
        if self.mode not in ['trade', 'test']:
            logger.error(f"O método 'run' não pode ser chamado em modo '{self.mode}'. Use 'run_backtest'.")
            return

        self.is_running = True
        logger.info(f"🚀 --- LOOP DE TRADING REAL/TESTE INICIADO PARA O SÍMBOLO {self.symbol} --- 🚀")

        while self.is_running:
            try:
                current_price = self.exchange_manager.get_current_price(self.symbol)
                if not current_price:
                    logger.error("Não foi possível obter o preço atual. A saltar ciclo.")
                    time.sleep(10)
                    continue
                
                logger.info(f"Preço atual de {self.symbol}: ${current_price:,.2f}")
                self.position_manager.process_manual_commands()
                self.position_manager.manage_positions(current_price)
                self.log_current_state()

                logger.info("--- Ciclo concluído. A aguardar 10 segundos... ---")
                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("\n[SHUTDOWN] Ctrl+C detectado. A parar o loop principal...")
                self.is_running = False
            except Exception as e:
                logger.critical(f"❌ Ocorreu um erro crítico no loop principal: {e}", exc_info=True)
                time.sleep(300)

    def run_backtest(self):
        """
        Executa a lógica de backtesting usando dados históricos do banco de dados.
        """
        if self.mode != 'backtest':
            logger.error(f"O método 'run_backtest' só pode ser chamado em modo 'backtest'.")
            return

        logger.info(f"🚀 --- INICIANDO PROCESSO DE BACKTEST PARA O SÍMBOLO {self.symbol} --- 🚀")
        self.is_running = True
        
        # 1. Limpa os trades antigos para um backtest limpo
        self.db_manager.clear_all_trades()
        logger.info("Trades antigos do backtest foram limpos.")

        # 2. Carrega os dados históricos
        # TODO: Ajustar os parâmetros (intervalo, data de início) conforme necessário
        historical_data = self.data_manager.get_master_table()
        if historical_data.empty:
            logger.error("Nenhuma dado histórico encontrado na master_table. Encerrando backtest.")
            return
        logger.info(f"{len(historical_data)} registos históricos carregados para o backtest.")

        # 3. Itera sobre os dados e simula a estratégia
        logger.info("Simulando a estratégia sobre os dados históricos...")
        initial_balance = self.account_manager.usdt_balance

        # Inicializa o rastreador de preço com o primeiro preço dos dados
        self.position_manager.recent_high_price = historical_data['close'].iloc[0]

        for index, row in historical_data.iterrows():
            current_price = row['close']
            # A sua lógica de gestão de posições é chamada para cada ponto de dados
            self.position_manager.manage_positions(current_price)

        # 4. Calcula e exibe os resultados
        logger.info("--- Backtest Concluído. A calcular resultados... ---")
        final_balance = self.account_manager.usdt_balance
        pnl = final_balance - initial_balance
        pnl_percent = (pnl / initial_balance) * 100 if initial_balance > 0 else 0
        
        all_trades = self.db_manager.get_all_trades()
        closed_trades = all_trades[all_trades['status'] == 'CLOSED']
        
        logger.info("========== RESULTADOS DO BACKTEST ==========")
        logger.info(f"Saldo Inicial: ${initial_balance:,.2f}")
        logger.info(f"Saldo Final:   ${final_balance:,.2f}")
        logger.info(f"Lucro/Prejuízo Total: ${pnl:,.2f} ({pnl_percent:.2f}%)")
        logger.info(f"Total de Trades Fechados: {len(closed_trades)}")
        logger.info("==========================================")

        self.is_running = False

    def shutdown(self):
        """Lida com todas as operações de limpeza para garantir uma saída limpa."""
        print("\n[SHUTDOWN] Iniciando o procedimento de desligamento gracioso...")
        if hasattr(self, 'db_manager') and self.db_manager:
            self.db_manager.close_client()
            print("[SHUTDOWN] Cliente InfluxDB fechado.")

        if self.mode in ['trade', 'test'] and hasattr(self, 'exchange_manager') and self.exchange_manager:
            self.exchange_manager.close_connection()
            print("[SHUTDOWN] Conexão com a exchange fechada.")

        print("[SHUTDOWN] Limpeza completa. Adeus!")

    def log_current_state(self):
        """Salva o estado atual do bot em um arquivo JSON para a UI ler."""
        if self.mode not in ['trade', 'test']:
            return

        open_positions = self.db_manager.get_open_positions()

        # CORREÇÃO: Converte Timestamps para strings antes de serializar
        if not open_positions.empty and 'timestamp' in open_positions.columns:
            open_positions['timestamp'] = open_positions['timestamp'].apply(
                lambda x: x.isoformat() if pd.notna(x) else None
            )

        positions_list = open_positions.to_dict(orient='records') if not open_positions.empty else []

        state = {
            "timestamp": time.time(),
            "is_running": self.is_running,
            "mode": self.mode,
            "open_positions": positions_list,
            "recent_high_price": self.position_manager.recent_high_price if self.position_manager else None
        }

        os.makedirs("/app/logs", exist_ok=True)
        with open("/app/logs/trading_status.json", "w") as f:
            # Usar um default handler no json.dump é uma alternativa, mas a conversão explícita é mais clara.
            json.dump(state, f, indent=4)
