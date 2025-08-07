import time
import pandas as pd
import json
import os
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.bot.position_manager import PositionManager
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.bot.account_manager import AccountManager
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.database.data_manager import DataManager
from jules_bot.core.market_data_provider import MarketDataProvider

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

    def credit_btc(self, quantity_btc):
        """Adiciona BTC ao saldo (usado pelo PositionManager após uma compra simulada)."""
        self.btc_balance += quantity_btc
        logger.info(f"[SIMULADOR] Saldo BTC creditado: +{quantity_btc:.8f}. Novo Saldo: {self.btc_balance:.8f} BTC.")

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

    def __init__(self,
                 mode: str,
                 bot_id: str,
                 market_data_provider: MarketDataProvider,
                 db_manager=None,
                 exchange_manager=None):

        self.mode = mode
        self.bot_id = bot_id
        self.is_running = True

        # === Injected Dependencies ===
        self.market_data_provider = market_data_provider

        # This logic remains the same: create managers if not provided (for live/test)
        self.db_manager = db_manager or self._create_db_manager_from_config(mode)
        self.exchange_manager = exchange_manager or ExchangeManager(mode=self.mode)

        # The PositionManager will also need the data provider to value positions
        self.position_manager = PositionManager(
            db_manager=self.db_manager,
            exchange_manager=self.exchange_manager,
            market_data_provider=self.market_data_provider
        )
        self.symbol = config_manager.get('APP', 'symbol')

    def _create_db_manager_from_config(self, mode):
        """Creates a DatabaseManager instance from the configuration."""
        db_config = config_manager.get_section('INFLUXDB')
        if mode == 'test':
            db_config['bucket'] = 'jules_bot_test_v1'
        elif mode == 'backtest':
            db_config['bucket'] = 'jules_bot_backtest_v1'
        return DatabaseManager(config=db_config)

    def run_single_cycle(self):
        """Executes one iteration of the bot's logic."""
        # 1. Get latest market data for strategy calculation
        # For a live bot, this would be a short range (e.g., start='-24h')
        # For a backtest, this step is handled by the mock exchange's price feed
        if self.mode in ['trade', 'test']:
            market_data_df = self.market_data_provider.get_historical_data(
                symbol="BTC/USD",
                start="-48h" # Example: strategy needs last 48h of data
            )

            # 2. Feed data to the strategy to get a signal (buy/sell/hold)
            # signal = self.strategy.generate_signal(market_data_df)

        # 3. Manage positions based on the signal
        current_price = self.exchange_manager.get_current_price(self.symbol)
        if not current_price:
            logger.error("Não foi possível obter o preço atual. A saltar ciclo.")
            return

        logger.info(f"Preço atual de {self.symbol}: ${current_price:,.2f}")
        self.position_manager.process_manual_commands()
        self.position_manager.manage_positions(current_price)

        # 4. Persist current state
        self.persist_current_state()

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
                self.run_single_cycle()
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

        # 2. Carrega os dados históricos da tabela mestre de features
        logger.info("A carregar dados históricos da 'features_master_table'...")
        historical_data = self.data_manager.read_data_from_influx(
            measurement="features_master_table",
            start_date="-90d" # Carrega os últimos 90 dias para o backtest
        )
        if historical_data.empty:
            logger.error("Nenhum dado histórico encontrado na 'features_master_table'. Encerrando backtest.")
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
        
        all_trades = self.db_manager.get_all_trades_in_range() # Use the correct method
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

    def persist_current_state(self):
        """Salva o estado atual do bot em um arquivo JSON para a UI ler."""
        if self.mode not in ['trade', 'test']:
            return

        open_positions_df = self.db_manager.get_open_positions()

        if not open_positions_df.empty:
            # Convert timestamp for JSON serialization
            open_positions_df['timestamp'] = open_positions_df['timestamp'].apply(lambda x: x.isoformat() if pd.notna(x) else None)
            positions_list = open_positions_df.to_dict(orient='records')
        else:
            positions_list = []

        # Calculate portfolio value
        # This is a simplified calculation. A real one would be more complex.
        portfolio_value = self.account_manager.usdt_balance if hasattr(self.account_manager, 'usdt_balance') else 0

        state = {
            "timestamp": time.time(),
            "bot_id": self.bot_id,
            "is_running": self.is_running,
            "mode": self.mode,
            "open_positions_count": len(positions_list),
            "portfolio_value_usd": portfolio_value,
            "open_positions": positions_list,
            "recent_high_price": self.position_manager.recent_high_price if self.position_manager else None
        }

        # Write bot status to database
        status_data = {
            "is_running": state['is_running'],
            "session_pnl_usd": 0, # Placeholder for now
            "session_pnl_percent": 0, # Placeholder for now
            "open_positions": state['open_positions_count'],
            "portfolio_value_usd": state['portfolio_value_usd']
        }
        self.db_manager.write_bot_status(self.bot_id, self.mode, status_data)

        os.makedirs("/app/logs", exist_ok=True)
        with open("/app/logs/trading_status.json", "w") as f:
            json.dump(state, f, indent=4)
