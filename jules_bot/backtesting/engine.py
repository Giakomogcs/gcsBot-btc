import pandas as pd
from tqdm import tqdm
import time
from jules_bot.utils.logger import logger
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.database.data_manager import DataManager
from jules_bot.bot.position_manager import PositionManager
from jules_bot.bot.account_manager import AccountManager

def run_backtest(ipc_queue, config):
    """
    The core backtesting logic loop.
    This function runs in a completely separate process.
    It sends message dictionaries back to the main UI process via the IPC queue.
    """
    try:
        ipc_queue.put({'type': 'log', 'message': 'Backtest worker process started...'})

        # --- Master Builder: Instanciando e Injetando Dependências ---
        db_manager = DatabaseManager(execution_mode='backtest')
        data_manager = DataManager(db_manager=db_manager, config=config, logger=logger)
        account_manager = AccountManager(binance_client=None)

        # Limpa o histórico de trades do ambiente de backtest
        ipc_queue.put({'type': 'log', 'message': 'Cleaning up previous backtest trade history...'})
        start_clean = "1970-01-01T00:00:00Z"
        stop_clean = pd.Timestamp.now(tz='UTC').isoformat()
        predicate = f'_measurement="trades" AND environment="backtest"'
        db_manager._client.delete_api().delete(start_clean, stop_clean, predicate, bucket=config.database.bucket, org=config.database.org)

        ipc_queue.put({'type': 'log', 'message': 'Loading data for backtest...'})
        df_features = data_manager.read_data_from_influx(
            measurement="features_master_table",
            start_date=config.backtest.start_date
        )

        if df_features.empty:
            ipc_queue.put({'type': 'error', 'message': "A 'features_master_table' está vazia. Abortando."})
            return

        position_manager = PositionManager(
            config=config,
            db_manager=db_manager,
            logger=logger,
            account_manager=account_manager
        )

        initial_capital = config.backtest.initial_capital
        capital = initial_capital
        btc_treasury = 0.0

        total_steps = len(df_features)
        ipc_queue.put({'type': 'log', 'message': f"Starting simulation with {total_steps} candles..."})

        for i, (timestamp, candle) in enumerate(df_features.iterrows()):
            # 1. VERIFICAR SAÍDAS
            closed_trades = position_manager.check_and_close_positions(candle)
            if closed_trades:
                for trade in closed_trades:
                    capital += trade['pnl_usdt']
                    btc_treasury += trade['quantity_btc_remaining']
                    ipc_queue.put({'type': 'new_closed_trade', 'data': trade})
                    ipc_queue.put({'type': 'log', 'message': f"[{timestamp.date()}] Posição FECHADA. P&L: ${trade['pnl_usdt']:.2f}"})

            # 2. VERIFICAR ENTRADAS
            buy_decision = position_manager.check_for_entry(candle)
            if buy_decision:
                trade_size_usdt = position_manager.get_capital_per_trade(capital)
                if trade_size_usdt <= capital:
                    buy_decision['trade_size_usdt'] = trade_size_usdt
                    position_manager.open_position(candle, buy_decision)
                    commission = trade_size_usdt * config.backtest.commission_rate
                    capital -= (trade_size_usdt + commission)
                    ipc_queue.put({'type': 'log', 'message': f"[{timestamp.date()}] Posição ABERTA. Custo: ${trade_size_usdt:.2f}"})

            # Send progress updates
            if i % 20 == 0: # Don't send too frequently
                progress_percentage = (i + 1) / total_steps
                ipc_queue.put({'type': 'progress', 'value': progress_percentage})

        # --- Final Results ---
        final_price = df_features.iloc[-1]['close']
        final_btc_value_usdt = btc_treasury * final_price
        final_total_portfolio_value = capital + final_btc_value_usdt
        pnl_total = final_total_portfolio_value - initial_capital
        pnl_percent = (pnl_total / initial_capital) * 100 if initial_capital > 0 else 0

        final_results = {
            'initial_capital': initial_capital,
            'final_capital_usdt': capital,
            'final_btc_treasury': btc_treasury,
            'final_btc_value_usdt': final_btc_value_usdt,
            'final_total_portfolio_value': final_total_portfolio_value,
            'pnl_total_usdt': pnl_total,
            'pnl_percent': pnl_percent
        }
        ipc_queue.put({'type': 'finished', 'data': final_results})

    except Exception as e:
        import traceback
        error_msg = f"Backtest worker process failed: {e}\n{traceback.format_exc()}"
        ipc_queue.put({'type': 'error', 'message': error_msg})

    ipc_queue.put({'type': 'log', 'message': 'Backtest worker process finished.'})
