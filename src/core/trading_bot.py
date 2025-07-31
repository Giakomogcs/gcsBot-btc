# src/trading_bot.py (VERSÃO 9.0 - FINAL, SINCRONIZADO E CONFIGURÁVEL)

import pandas as pd
import numpy as np
import joblib
import os
import time
import csv
import json
import signal
import sys
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from datetime import datetime, timezone, timedelta
from collections import deque
from typing import Tuple, Any

from src.logger import logger
from src.config_manager import settings
from src.core.position_manager import PositionManager
from src.data_manager import DataManager
from src.core.confidence_manager import AdaptiveConfidenceManager
from src.core.display_manager import display_trading_dashboard
from src.core.rl_agent import BetSizingAgent
from src.core.treasury_manager import TreasuryManager
from src.core.anomaly_detector import AnomalyDetector
from src.core.optimizer import WalkForwardOptimizer
from src.core.account_manager import AccountManager

from typing import Any, Dict, Optional, Tuple
from dateutil.parser import isoparse

class PortfolioManager:
    """A class to manage the portfolio."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        """
        Initializes the PortfolioManager class.

        Args:
            client: The Binance client.
        """
        self.client = self.data_manager.client
        self.account_manager = AccountManager(self.client)
        self.data_manager = DataManager(db_url)
        self.portfolio = PortfolioManager(self.client)
        self.position_manager = PositionManager(settings) 
        self.max_usdt_allocation = settings.MAX_USDT_ALLOCATION
        self.trading_capital_usdt = 0.0
        self.trading_btc_balance = 0.0
        self.long_term_btc_holdings = 0.0
        self.initial_total_value_usdt = 1.0
        self.session_peak_value = 0.0

        self.models, self.scalers, self.strategy_params = {}, {}, {}

    def sync_with_live_balance(self):
        if not self.client:
            logger.error("Cliente Binance indisponível para sincronização de saldo.")
            return False
        try:
            logger.info("📡 Sincronizando com o saldo real da conta Binance...")
            account_info = self.client.get_account()
            usdt_balance_obj = next((item for item in account_info['balances'] if item['asset'] == 'USDT'), {'free': '0'})
            self.trading_capital_usdt = min(float(usdt_balance_obj['free']), self.max_usdt_allocation)
            self.trading_btc_balance = 0.0 
            self.long_term_btc_holdings = 0.0
            self.initial_total_value_usdt = self.trading_capital_usdt if self.trading_capital_usdt > 0 else 1.0
            logger.info("✅ Portfólio Sincronizado com Saldo Real.")
            return True
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Falha ao sincronizar com o saldo da Binance: {e}", exc_info=True)
            return False

    def get_current_price(self):
        try:
            return float(self.client.get_symbol_ticker(symbol=settings.SYMBOL)['price'])
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            logger.error(f"Não foi possível obter o preço atual de {settings.SYMBOL}: {e}")
            return None

    def update_on_buy(self, bought_btc_amount, cost_usdt):
        self.trading_capital_usdt -= cost_usdt
        self.trading_btc_balance += bought_btc_amount

    def update_on_sell(self, sold_btc_amount, revenue_usdt, profit_usdt, price, params):
        self.trading_btc_balance -= sold_btc_amount
        reinvested_usdt = revenue_usdt
        if profit_usdt > 0:
            treasury_usdt = profit_usdt * params.get('treasury_allocation_pct', 0.20)
            reinvested_usdt -= treasury_usdt
            self.long_term_btc_holdings += treasury_usdt / price if price > 0 else 0
            logger.info(f"💰 Lucro de ${profit_usdt:,.2f}! Alocando ${treasury_usdt:,.2f} para Tesouraria.")
        self.trading_capital_usdt += reinvested_usdt
        
    def update_on_dca(self, bought_btc_amount, cost_usdt):
        self.trading_capital_usdt -= cost_usdt
        self.long_term_btc_holdings += bought_btc_amount

    def get_total_portfolio_value_usdt(self, current_btc_price):
        if not current_btc_price or current_btc_price <= 0: return self.trading_capital_usdt
        return self.trading_capital_usdt + (self.trading_btc_balance * current_btc_price) + (self.long_term_btc_holdings * current_btc_price)

from typing import Optional

class TradingBot:
    """The main class for the trading bot."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        """
        Initializes the TradingBot class.

        Args:
            db_url: The database URL. If not provided, it will be read from the DATABASE_URL environment variable.
        """
        self.data_manager = DataManager(db_url)
        self.client = self.data_manager.client
        self.portfolio = PortfolioManager(self.client)
        self.models, self.scalers, self.strategy_params = {}, {}, {}
        self.confidence_managers = {}
        self.regime_map = {}
        self.model_feature_names = []
        
        self.last_used_params = {}
        self.session_peak_value = 0.0
        self.session_trades, self.session_wins, self.session_total_pnl_usdt = 0, 0, 0.0
        self.session_drawdown_stop_activated = False
        
        # === MUDANÇA 1: Usar o parâmetro de segurança do config ===
        self.SESSION_MAX_DRAWDOWN = settings.SESSION_MAX_DRAWDOWN
        
        self.last_dca_time = None
        self.last_event_message = "Inicializando o bot..."
        self.specialist_stats = {}
        self.rl_agent = BetSizingAgent(n_situations=10, n_bet_sizes=5)
        self.treasury_manager = TreasuryManager()
        self.anomaly_detector = AnomalyDetector()
        self.performance_history = {}
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def _check_model_validity(self) -> bool:
        """
        Checks if the model is valid.

        Returns:
            True if the model is valid, False otherwise.
        """
        if not os.path.exists(settings.MODEL_METADATA_FILE):
            logger.error("Nenhum modelo encontrado. Rode 'python run.py optimize' primeiro.")
            return False
        try:
            with open(settings.MODEL_METADATA_FILE, 'r') as f:
                metadata = json.load(f)
            valid_until = isoparse(metadata.get("valid_until"))
            if datetime.now(timezone.utc) > valid_until:
                logger.error(f"O modelo atual expirou. Rode 'python run.py optimize' para criar um novo.")
                return False
            else:
                logger.info(f"✅ Modelo está válido. Expira em: {(valid_until - datetime.now(timezone.utc)).days} dias.")
                return True
        except Exception as e:
            logger.error(f"Erro ao ler metadados do modelo: {e}. Rode 'optimize' por segurança.")
            return False

    def _load_all_models(self) -> bool:
        """
        Loads all the models.

        Returns:
            True if the models were loaded successfully, False otherwise.
        """
        try:
            with open(settings.MODEL_METADATA_FILE, 'r') as f: metadata = json.load(f)
            self.model_feature_names = metadata['feature_names']
            summary = metadata.get('optimization_summary', {})
            
            loaded_models_count = 0
            for situation, result in summary.items():
                if result.get('status') == 'Optimized and Saved':
                    try:
                        self.models[situation] = joblib.load(os.path.join(settings.DATA_DIR, result['model_file']))
                        self.scalers[situation] = joblib.load(os.path.join(settings.DATA_DIR, result['scaler_file']))
                        with open(os.path.join(settings.DATA_DIR, result['params_file']), 'r') as p:
                            self.strategy_params[situation] = json.load(p)
                        loaded_models_count += 1
                    except Exception as e:
                        logger.error(f"Falha ao carregar artefatos para '{situation}': {e}")
            
            if not self.models:
                logger.error("ERRO CRÍTICO: Nenhum modelo foi carregado. Execute a otimização.")
                return False
            logger.info(f"✅ {loaded_models_count} modelo(s) únicos carregados e prontos para operar.")
            return True
        except Exception as e:
            logger.error(f"Erro fatal ao carregar modelos: {e}", exc_info=True)
            return False


    def _get_active_model(self, situation: int) -> Tuple[Any, Any, Any, Any]:
        """
        Gets the active model for a given situation.

        Args:
            situation: The current market situation.

        Returns:
            A tuple with the model, the scaler, the parameters, and the confidence manager.
        """
        situation_name = f"SITUATION_{situation}"
        if situation_name not in self.models:
            return None, None, None, None
        
        model = self.models.get(situation_name)
        scaler = self.scalers.get(situation_name)
        params = self.strategy_params.get(situation_name)
        
        if situation_name not in self.confidence_managers:
            self.confidence_managers[situation_name] = AdaptiveConfidenceManager(**params)

        confidence_manager = self.confidence_managers.get(situation_name)
        return model, scaler, params, confidence_manager

    def run(self) -> None:
        """Runs the trading bot."""
        if not self._check_model_validity(): return
        if not self._load_all_models(): return
        self.anomaly_detector.train(self.data_manager.update_and_load_data(settings.SYMBOL, '1m'), self.model_feature_names)
        self.data_manager.db.create_table('trades', [
            'timestamp TIMESTAMP',
            'type VARCHAR(10)',
            'price FLOAT',
            'quantity FLOAT',
            'pnl_usdt FLOAT',
            'pnl_percent FLOAT',
            'reason VARCHAR(255)'
        ])
        self.data_manager.db.create_table('bot_state', [
            'state_key VARCHAR(255) PRIMARY KEY',
            'state_value JSON'
        ])
        self.data_manager.db.create_table('model_metrics', [
            'timestamp TIMESTAMP',
            'model_name VARCHAR(255)',
            'accuracy FLOAT',
            'precision FLOAT',
            'recall FLOAT',
            'f1_score FLOAT',
            'roc_auc FLOAT'
        ])
        if not self._load_state():
            if not self.portfolio.sync_with_live_balance():
                logger.critical("Falha fatal ao inicializar portfólio. Encerrando."); return
            self.session_peak_value = self.portfolio.initial_total_value_usdt
        
        while True:
            try:
                processed_df = self.data_manager.update_and_load_data(settings.SYMBOL, '1m')
                if processed_df.empty: time.sleep(60); continue
                latest_data = processed_df.iloc[-1]
                
                self._check_and_manage_drawdown(latest_data)
                if self.session_drawdown_stop_activated:
                    logger.warning("Circuit Breaker ATIVO. Novas operações suspensas."); time.sleep(300); continue
                
                # 1. VERIFICAR SAÍDAS: O Position Manager verifica se alguma posição aberta atingiu o alvo.
                closed_trades = self.position_manager.check_and_close_positions(latest_data)
                if closed_trades:
                    logger.info(f"Processando {len(closed_trades)} posições fechadas.")
                    for trade_summary in closed_trades: # Mude 'trade' para 'trade_summary'
                        logger.info(f"Posição fechada: {trade_summary}")
                        # A chamada agora corresponde à nova assinatura da função
                        self._execute_sell(trade_summary, latest_data) 

                # 2. VERIFICAR ENTRADAS: Se houver 'slots' disponíveis, procuramos por um sinal de entrada.
                max_trades = settings.position_management.max_concurrent_trades
                # Use o novo método para contar as posições
                if self.position_manager.get_open_positions_count() < max_trades: 
                    self._check_for_entry_signal(latest_data)
                else:
                    self.last_event_message = f"Aguardando (limite de {max_trades} posições atingido)."

                # A lógica de DCA pode continuar aqui, talvez com uma condição adicional
                self._handle_dca_opportunity(latest_data)

                self.treasury_manager.track_progress(self.portfolio.long_term_btc_holdings)
                self._check_model_performance()
                status_data = self._build_status_data(latest_data)
                display_trading_dashboard(status_data)
                self._save_state()
                time.sleep(60)
            except KeyboardInterrupt: self.graceful_shutdown(None, None)
            except Exception as e: logger.error(f"Erro inesperado no loop: {e}", exc_info=True); time.sleep(60)

    def _check_and_manage_drawdown(self, latest_data: pd.Series) -> None:
        """
        Checks and manages the drawdown.

        Args:
            latest_data: The latest data.
        """
        current_price = latest_data['close']
        current_total_value = self.portfolio.get_total_portfolio_value_usdt(current_price)
        if current_total_value:
            self.session_peak_value = max(self.session_peak_value, current_total_value)
            self.portfolio.session_peak_value = self.session_peak_value
            session_drawdown = (current_total_value - self.session_peak_value) / self.session_peak_value if self.session_peak_value > 0 else 0
            if not self.session_drawdown_stop_activated and session_drawdown < self.SESSION_MAX_DRAWDOWN:
                self.last_event_message = f"CIRCUIT BREAKER! Drawdown de {session_drawdown:.2%}"
                logger.critical(self.last_event_message)
                self.session_drawdown_stop_activated = True
                if self.in_trade_position: self._execute_sell(current_price, "Circuit Breaker", latest_data)

    # ... (O restante do arquivo permanece idêntico) ...
    def _manage_active_position(self, latest_data: pd.Series) -> None:
        """
        Manages the active position.

        Args:
            latest_data: The latest data.
        """
        price = latest_data['close']
        self.highest_price_in_trade = max(self.highest_price_in_trade, price)
        pnl_pct = (price / self.buy_price - 1) if self.buy_price > 0 else 0
        pnl_usdt = (price - self.buy_price) * self.portfolio.trading_btc_balance
        self.last_event_message = f"Em trade. P&L: {pnl_pct:+.2%} (${pnl_usdt:,.2f})"

        if price <= self.current_stop_price:
            self._execute_sell(price, f"Stop Loss ({pnl_pct:.2%})", latest_data); return
        
        params = self.last_used_params
        if self.position_phase == 'INITIAL' and price >= self.buy_price * (1 + params.get('profit_threshold', 0.01) / 2):
            self.position_phase = 'TRAILING'
            new_stop = self.buy_price * (1 + (settings.FEE_RATE + settings.SLIPPAGE_RATE) * 2)
            self.current_stop_price = max(self.current_stop_price, new_stop)
            self.last_event_message = f"Posição em Breakeven. Stop: ${self.current_stop_price:,.2f}"
            logger.info(self.last_event_message)
        elif self.position_phase == 'TRAILING':
            new_trailing_stop = self.highest_price_in_trade * (1 - (latest_data['atr']/price * params.get('trailing_stop_multiplier', 1.5)))
            if new_trailing_stop > self.current_stop_price:
                self.current_stop_price = new_trailing_stop
                self.last_event_message = f"Trailing Stop ajustado para ${self.current_stop_price:,.2f}"
                logger.info(self.last_event_message)

    def _check_for_entry_signal(self, latest_data: pd.Series) -> bool:
        """
        Checks for an entry signal.

        Args:
            latest_data: The latest data.

        Returns:
            True if an entry signal is found, False otherwise.
        """
        situation = latest_data['market_situation']
        model, scaler, params, confidence_manager = self._get_active_model(situation)

        if not all([model, scaler, params, confidence_manager]):
            self.last_event_message = f"Aguardando (sem modelo para situação {situation})."; return False
        
        # Anomaly detection
        is_anomaly = self.anomaly_detector.predict(pd.DataFrame([latest_data]), self.model_feature_names)[0] == -1
        if is_anomaly:
            self.last_event_message = "Anomalia detectada. Nenhuma ação será tomada."; return False

        if latest_data.get('volume', 0) < latest_data.get('volume_sma_50', 0):
            self.last_event_message = "Aguardando (volume baixo)."; return False

        features_for_prediction = pd.DataFrame([latest_data[self.model_feature_names]])
        scaled_features = scaler.transform(features_for_prediction)
        buy_confidence = model.predict_proba(scaled_features)[0][1]
        
        base_threshold = 0.55

        # Profit-seeking escalation
        if self.session_wins > 0 and self.session_trades > 0 and self.session_wins == self.session_trades:
            profit_seeking_escalation = 1 - (self.session_wins * 0.01)
            base_threshold *= profit_seeking_escalation

        # Loss-aversion escalation
        if self.session_trades > 0 and self.session_wins < self.session_trades:
            loss_aversion_escalation = 1 + ((self.session_trades - self.session_wins) * 0.02)
            base_threshold *= loss_aversion_escalation

        # Volatility modifier
        volatility_modifier = 1 + (latest_data['volatility_ratio'] * 0.1)
        final_threshold = base_threshold * volatility_modifier

        self.last_event_message = f"Aguardando... Confiança: {buy_confidence:.2%} (Alvo: {final_threshold:.2%})"

        if buy_confidence > final_threshold:
            state = self.rl_agent.get_state(situation, buy_confidence)
            action = self.rl_agent.get_action(state)
            bet_size = self.rl_agent.get_bet_size(action)
            trade_size_usdt = self.portfolio.trading_capital_usdt * bet_size

            if trade_size_usdt < 10: return False
            
            self.last_event_message = f"SINAL DE COMPRA! Confiança: {buy_confidence:.1%}. Abrindo posição..."
            logger.info(self.last_event_message)

            # O PositionManager regista a intenção de abrir a posição.
            # Usamos 'LONG' como padrão por enquanto.
            # O PositionManager regista a intenção de abrir a posição.
            self.position_manager.open_position(entry_candle=latest_data, signal='LONG')

            # --- LÓGICA DE DIMENSIONAMENTO DINÂMICO ---
            available_capital = self.account_manager.get_quote_asset_balance()
            trade_size_usdt = self.position_manager.get_capital_per_trade(available_capital)

            # Garante que temos capital e que o valor é válido para a exchange
            if trade_size_usdt > 10: 
                qty_to_buy = trade_size_usdt / latest_data['close']
                self._execute_buy(latest_data['close'], trade_size_usdt, latest_data)
                self.position_manager.open_position(entry_price=latest_data['close'], quantity_btc=qty_to_buy)
            else:
                logger.warning(f"Capital insuficiente ou risco dinâmico baixo para abrir posição. Calculado: ${trade_size_usdt:,.2f} USDT")

            return True
        return False

    def _handle_dca_opportunity(self, latest_data: pd.Series) -> None:
        """
        Handles the dollar-cost averaging opportunity.

        Args:
            latest_data: The latest data.
        """
        amount_to_buy_usdt = self.treasury_manager.smart_accumulation(
            latest_data,
            self.portfolio.trading_capital_usdt,
            self.session_wins,
            self.session_trades
        )
        if amount_to_buy_usdt == 0:
            return

        try:
            self.last_event_message = f"Executando Acumulação Inteligente de ${amount_to_buy_usdt:,.2f}..."
            logger.info(self.last_event_message)
            
            cost = amount_to_buy_usdt
            if not self.client or settings.USE_TESTNET:
                buy_price_eff = latest_data['close'] * (1 + settings.SLIPPAGE_RATE)
                qty_bought = cost / buy_price_eff
                cost_with_fees = cost * (1 + settings.FEE_RATE)
                self._log_trade("DCA (SIM)", buy_price_eff, qty_bought, "Acumulação em baixa")
            else:
                order = self.client.create_order(symbol=settings.SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=round(cost, 2))
                qty_bought, cost_with_fees = float(order['executedQty']), float(order['cummulativeQuoteQty'])
                buy_price_eff = cost_with_fees / qty_bought if qty_bought > 0 else latest_data['close']
                self._log_trade("DCA (REAL)", buy_price_eff, qty_bought, "Acumulação em baixa")
            
            self.portfolio.update_on_dca(qty_bought, cost_with_fees)
            self.last_dca_time = datetime.now(timezone.utc)
        except Exception as e:
            self.last_event_message = "Falha na compra de DCA."
            logger.error(f"ERRO AO EXECUTAR COMPRA DE DCA: {e}", exc_info=True)

    def _log_trade(self, trade_type, price, qty, reason, pnl_usdt=0, pnl_pct=0):
        trade_data = {
            'timestamp': datetime.now(timezone.utc),
            'type': trade_type,
            'price': price,
            'quantity': qty,
            'pnl_usdt': pnl_usdt,
            'pnl_percent': pnl_pct,
            'reason': reason
        }
        df = pd.DataFrame([trade_data])
        self.data_manager.db.insert_dataframe(df, 'trades')

    def _execute_buy(self, price: float, trade_size_usdt: float, latest_data: pd.Series) -> None:
        """
        Executa uma ordem de compra.
        """
        try:
            self.last_event_message = f"COMPRANDO ${trade_size_usdt:,.2f}"
            logger.info(self.last_event_message)

            if not self.client or settings.app.use_testnet:
                buy_price = price * (1 + settings.SLIPPAGE_RATE)
                qty = trade_size_usdt / buy_price
                cost = trade_size_usdt * (1 + settings.FEE_RATE + settings.IOF_RATE)
                self.portfolio.update_on_buy(qty, cost)
                self._log_trade("BUY (SIM)", buy_price, qty, f"Sinal ML")
            else:
                # A lógica de ordem real será adicionada aqui depois
                pass

            # A posição já foi aberta no PositionManager.
            # No futuro, podemos passar o ID do trade para o log, etc.

        except Exception as e:
            logger.error(f"ERRO AO EXECUTAR COMPRA: {e}", exc_info=True)
            

    def _execute_sell(self, trade_summary: dict, latest_data: pd.Series) -> None:
        """
        Executa uma ordem de venda baseada num trade fechado pelo PositionManager.
        """
        # No futuro, a quantidade a vender virá do trade_summary quando o
        # sistema de capital por trade estiver implementado. Por agora, vendemos tudo.
        amount_to_sell = self.portfolio.trading_btc_balance 
        if amount_to_sell <= 0: return

        try:
            reason = trade_summary['exit_reason']
            sell_price = trade_summary['exit_price']

            self.last_event_message = f"VENDENDO. Motivo: {reason}"
            logger.info(self.last_event_message)

            pnl_usdt, pnl_pct, actual_sell_price = 0, 0, sell_price

            if not self.client or settings.app.use_testnet:
                actual_sell_price = sell_price * (1 - settings.SLIPPAGE_RATE)
                revenue = actual_sell_price * amount_to_sell
                buy_cost = trade_summary['entry_price'] * amount_to_sell
                pnl_usdt = (revenue * (1 - settings.FEE_RATE)) - (buy_cost * (1 + settings.IOF_RATE))
                pnl_pct = (actual_sell_price / trade_summary['entry_price'] - 1) if trade_summary['entry_price'] > 0 else 0
                self._log_trade("SELL (SIM)", actual_sell_price, amount_to_sell, reason, pnl_usdt, pnl_pct)
            else:
                # A lógica de ordem real será adicionada aqui depois
                pass 

            self.session_trades += 1
            if pnl_usdt > 0: self.session_wins += 1
            self.session_total_pnl_usdt += pnl_usdt

            # Aqui atualizamos o portfólio
            # self.portfolio.update_on_sell(...)

        except Exception as e: 
            logger.error(f"ERRO AO EXECUTAR VENDA: {e}", exc_info=True)


    def _update_specialist_stats(self, specialist_name: str, pnl_usdt: float) -> None:
        """
        Updates the specialist stats.

        Args:
            specialist_name: The name of the specialist.
            pnl_usdt: The PNL of the trade in USDT.
        """
        if not specialist_name: return
        if specialist_name not in self.specialist_stats:
            self.specialist_stats[specialist_name] = {'total_trades': 0, 'wins': 0, 'total_pnl': 0.0}
        
        stats = self.specialist_stats[specialist_name]
        stats['total_trades'] += 1
        stats['total_pnl'] += pnl_usdt
        if pnl_usdt > 0: stats['wins'] += 1

    def _check_model_performance(self) -> None:
        """Checks the model performance and triggers re-optimization if needed."""
        for situation_name, history in self.performance_history.items():
            if len(history) == 100:
                average_pnl = np.mean(history)
                if average_pnl < 0:
                    logger.warning(f"A performance do modelo para a situação {situation_name} está degradando. Acionando re-otimização...")
                    optimizer = WalkForwardOptimizer(self.data_manager.update_and_load_data(settings.SYMBOL, '1m'), self.model_feature_names)
                    situation_data = self.data_manager.update_and_load_data(settings.SYMBOL, '1m')
                    situation_data = situation_data[situation_data['market_situation'] == int(situation_name.split('_')[-1])]
                    optimizer.run_optimization_for_situation(situation_name, situation_data)
                    self.performance_history[situation_name].clear()

    def _check_and_manage_drawdown(self, latest_data: pd.Series) -> None:
        """
        Checks and manages the drawdown.

        Args:
            latest_data: The latest data.
        """
        current_price = latest_data['close']
        total_value = self.portfolio.get_total_portfolio_value_usdt(current_price)
        growth_pct = (total_value / self.portfolio.initial_total_value_usdt - 1) * 100 if self.portfolio.initial_total_value_usdt > 0 else 0
        situation = latest_data['market_situation']
        situation_name = f"SITUATION_{situation}"
        confidence_manager = self.confidence_managers.get(situation_name)
        last_op_situation_name = f"SITUATION_{self.last_used_params.get('entry_situation', 'N/A')}"
        recommendation = self.treasury_manager.is_it_worth_it(latest_data)

        return {
            "portfolio": { "current_price": current_price, "total_value_usdt": total_value, "session_growth_pct": growth_pct, "trading_capital_usdt": self.portfolio.trading_capital_usdt, "trading_btc_balance": self.portfolio.trading_btc_balance, "trading_btc_value_usdt": self.portfolio.trading_btc_balance * current_price, "long_term_btc_holdings": self.portfolio.long_term_btc_holdings, "long_term_value_usdt": self.portfolio.long_term_btc_holdings * current_price, },
            "session_stats": { "trades": self.session_trades, "wins": self.session_wins, "total_pnl_usdt": self.session_total_pnl_usdt, },
            "bot_status": { "market_situation": situation, "active_model": situation_name, "confidence_threshold": confidence_manager.get_confidence() if confidence_manager else 0, "last_event_message": self.last_event_message, "recommendation": recommendation },
            "last_operation": { "situation_name": last_op_situation_name, "pnl_pct": self.last_used_params.get('last_pnl_pct', 0.0), **self.specialist_stats.get(last_op_situation_name, {}) }
        }


    def _save_state(self):
        state = {
            'in_trade_position': self.in_trade_position, 'buy_price': self.buy_price, 'position_phase': self.position_phase,
            'current_stop_price': self.current_stop_price, 'highest_price_in_trade': self.highest_price_in_trade,
            'last_used_params': self.last_used_params, 'session_peak_value': self.session_peak_value,
            'session_drawdown_stop_activated': self.session_drawdown_stop_activated, 'session_trades': self.session_trades,
            'session_wins': self.session_wins, 'session_total_pnl_usdt': self.session_total_pnl_usdt,
            'last_dca_time': self.last_dca_time.isoformat() if self.last_dca_time else None,
            'specialist_stats': self.specialist_stats, 
            'portfolio': { 'trading_capital_usdt': self.portfolio.trading_capital_usdt, 'trading_btc_balance': self.portfolio.trading_btc_balance, 'long_term_btc_holdings': self.portfolio.long_term_btc_holdings, 'initial_total_value_usdt': self.portfolio.initial_total_value_usdt,},
        }
        df = pd.DataFrame([{'state_key': 'bot_state', 'state_value': json.dumps(state)}])
        self.data_manager.db.insert_dataframe(df, 'bot_state', if_exists='replace')

    def _load_state(self) -> bool:
        """
        Loads the bot's state from the database.

        Returns:
            True if the state was loaded successfully, False otherwise.
        """
        try:
            query = "SELECT state_value FROM bot_state WHERE state_key = 'bot_state'"
            state_df = self.data_manager.db.fetch_data(query)
            if state_df.empty:
                return False
            state = json.loads(state_df['state_value'][0])
            self.in_trade_position = state.get('in_trade_position', False)
            self.buy_price, self.position_phase = state.get('buy_price', 0.0), state.get('position_phase')
            self.current_stop_price, self.highest_price_in_trade = state.get('current_stop_price', 0.0), state.get('highest_price_in_trade', 0.0)
            self.last_used_params, self.session_peak_value = state.get('last_used_params', {}), state.get('session_peak_value', 0.0)
            self.session_drawdown_stop_activated = state.get('session_drawdown_stop_activated', False)
            self.session_trades, self.session_wins, self.session_total_pnl_usdt = state.get('session_trades', 0), state.get('session_wins', 0), state.get('session_total_pnl_usdt', 0.0)
            last_dca_time_str = state.get('last_dca_time')
            self.last_dca_time = datetime.fromisoformat(last_dca_time_str) if last_dca_time_str else None
            self.specialist_stats = state.get('specialist_stats', {}) 
            portfolio_state = state.get('portfolio', {})
            self.portfolio.trading_capital_usdt, self.portfolio.trading_btc_balance, self.portfolio.long_term_btc_holdings, self.portfolio.initial_total_value_usdt = portfolio_state.get('trading_capital_usdt', 0.0), portfolio_state.get('trading_btc_balance', 0.0), portfolio_state.get('long_term_btc_holdings', 0.0), portfolio_state.get('initial_total_value_usdt', 1.0)
            logger.info("✅ Estado anterior do bot e portfólio carregado com sucesso.")
            return True
        except Exception as e:
            logger.error(f"Não foi possível carregar o estado anterior: {e}. Iniciando com um estado limpo.")
            return False

    def graceful_shutdown(self, signum: int, frame: Any) -> None:
        """
        Gracefully shuts down the bot.

        Args:
            signum: The signal number.
            frame: The current stack frame.
        """
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO DE FORMA SEGURA... 🚨")
        self._save_state()
        logger.info("Estado do bot salvo. Desligando.")
        sys.exit(0)
