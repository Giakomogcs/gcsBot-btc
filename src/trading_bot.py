# src/trading_bot.py (VERSÃO 7.4 - Com Dashboard Corrigido)

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

from src.logger import logger
from src.config import (
    API_KEY, API_SECRET, USE_TESTNET, SYMBOL, DATA_DIR, TRADES_LOG_FILE,
    BOT_STATE_FILE, MAX_USDT_ALLOCATION, FEE_RATE, SLIPPAGE_RATE,
    MODEL_METADATA_FILE, DCA_IN_BEAR_MARKET_ENABLED, DCA_DAILY_AMOUNT_USDT,
    DCA_MIN_CAPITAL_USDT
)
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
from src.confidence_manager import AdaptiveConfidenceManager
from src.display_manager import display_trading_dashboard

class PortfolioManager:
    """Gerencia todo o capital, posições e a tesouraria de longo prazo."""
    def __init__(self, client):
        self.client = client
        self.max_usdt_allocation = MAX_USDT_ALLOCATION
        self.trading_capital_usdt = 0.0
        self.trading_btc_balance = 0.0
        self.long_term_btc_holdings = 0.0
        self.initial_total_value_usdt = 1.0 # Inicia com 1 para evitar divisão por zero
        self.session_peak_value = 0.0

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
            return float(self.client.get_symbol_ticker(symbol=SYMBOL)['price'])
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            logger.error(f"Não foi possível obter o preço atual de {SYMBOL}: {e}")
            return None

    def update_on_buy(self, bought_btc_amount, cost_usdt):
        self.trading_capital_usdt -= cost_usdt
        self.trading_btc_balance += bought_btc_amount

    def update_on_sell(self, sold_btc_amount, revenue_usdt, profit_usdt, price, params):
        self.trading_btc_balance -= sold_btc_amount
        reinvested_usdt = revenue_usdt
        
        if profit_usdt > 0:
            treasury_allocation = params.get('treasury_allocation_pct', 0.20)
            treasury_usdt = profit_usdt * treasury_allocation
            reinvested_usdt -= treasury_usdt
            
            treasury_btc_added = treasury_usdt / price if price > 0 else 0
            self.long_term_btc_holdings += treasury_btc_added
            logger.info(f"💰 Lucro de ${profit_usdt:,.2f}! Alocando ${treasury_usdt:,.2f} para Tesouraria.")

        self.trading_capital_usdt += reinvested_usdt
        
    def update_on_dca(self, bought_btc_amount, cost_usdt):
        self.trading_capital_usdt -= cost_usdt
        self.long_term_btc_holdings += bought_btc_amount

    def get_total_portfolio_value_usdt(self, current_btc_price):
        if current_btc_price is None or current_btc_price <= 0:
            return self.trading_capital_usdt
        
        trading_value = self.trading_capital_usdt + (self.trading_btc_balance * current_btc_price)
        holding_value = self.long_term_btc_holdings * current_btc_price
        return trading_value + holding_value


class TradingBot:
    def __init__(self):
        self.data_manager = DataManager()
        self.trainer = ModelTrainer()
        self.client = self.data_manager.client
        self.portfolio = PortfolioManager(self.client)
        self.models, self.scalers, self.strategy_params, self.confidence_managers = {}, {}, {}, {}
        self.model_feature_names = []
        self.in_trade_position = False
        self.buy_price = 0.0
        self.position_phase = None
        self.current_stop_price = 0.0
        self.highest_price_in_trade = 0.0
        self.last_used_params = {}
        self.session_peak_value = 0.0
        self.session_trades = 0
        self.session_wins = 0
        self.session_total_pnl_usdt = 0.0
        self.session_drawdown_stop_activated = False
        self.SESSION_MAX_DRAWDOWN = -0.15
        self.last_dca_time = None
        self.last_event_message = "Inicializando o bot..."

        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def load_all_specialists(self):
        try:
            logger.info(f"Procurando metadados dos modelos em: {MODEL_METADATA_FILE}")
            with open(MODEL_METADATA_FILE, 'r') as f: metadata = json.load(f)
            valid_until_str = metadata.get('valid_until')
            if not valid_until_str:
                logger.error("ERRO CRÍTICO: Data de validade não encontrada.")
                return False
            if datetime.now(timezone.utc) > datetime.fromisoformat(valid_until_str):
                logger.error("="*60 + "\n🚨 ALERTA: O CONJUNTO DE MODELOS ESTÁ EXPIRADO! 🚨\n" + "="*60)
                return False
            
            logger.info(f"✅ Conjunto de modelos válido. Verificação OK.")
            self.model_feature_names = metadata.get('feature_names', [])
            summary = metadata.get('optimization_summary', {})
            if not self.model_feature_names:
                logger.error("Metadados corrompidos: a lista de features está ausente.")
                return False
            
            logger.info(f"Carregando {len(self.model_feature_names)} features esperadas.")
            loaded_specialists_count = 0
            for regime, result in summary.items():
                if result.get('status') == 'Optimized and Saved':
                    try:
                        model_path = os.path.join(DATA_DIR, result['model_file'])
                        scaler_path = model_path.replace('trading_model', 'scaler')
                        params_path = os.path.join(DATA_DIR, result['params_file'])
                        self.models[regime] = joblib.load(model_path)
                        self.scalers[regime] = joblib.load(scaler_path)
                        with open(params_path, 'r') as p: self.strategy_params[regime] = json.load(p)
                        self.confidence_managers[regime] = AdaptiveConfidenceManager(
                            initial_confidence=self.strategy_params[regime].get('initial_confidence', 0.7),
                            learning_rate=self.strategy_params[regime].get('confidence_learning_rate', 0.05),
                            window_size=self.strategy_params[regime].get('confidence_window_size', 10),
                            pnl_clamp_value=self.strategy_params[regime].get('confidence_pnl_clamp', 0.02)
                        )
                        loaded_specialists_count += 1
                    except Exception as e:
                        logger.error(f"Falha ao carregar artefatos para o regime '{regime}': {e}")
            
            if loaded_specialists_count == 0:
                logger.error("="*60 + "\n❌ ERRO CRÍTICO: Nenhum especialista de trading foi carregado.\n" + "="*60)
                return False
            logger.info(f"✅ {loaded_specialists_count} especialista(s) carregado(s) e prontos para operar.")
            return True
        except Exception as e:
            logger.error(f"Erro ao carregar especialistas: {e}", exc_info=True)
            return False

    def run(self):
        if not self.load_all_specialists(): return
        self._initialize_trade_log()
        if not self._load_state():
            if not self.portfolio.sync_with_live_balance():
                logger.critical("Falha fatal ao inicializar portfólio. Encerrando."); return
            self.session_peak_value = self.portfolio.initial_total_value_usdt
            self.portfolio.session_peak_value = self.session_peak_value
        
        while True:
            try:
                features_df = self.data_manager.update_and_load_data(SYMBOL, '1m')
                if features_df.empty or len(features_df) < 200: time.sleep(60); continue
                processed_df, _ = self.trainer._prepare_features(features_df.copy())
                if processed_df.empty: time.sleep(60); continue

                latest_data = processed_df.iloc[-1]
                current_price = latest_data['close']
                regime = latest_data['market_regime']
                
                current_total_value = self.portfolio.get_total_portfolio_value_usdt(current_price)
                if current_total_value:
                    self.session_peak_value = max(self.session_peak_value, current_total_value)
                    self.portfolio.session_peak_value = self.session_peak_value
                    if not self.session_drawdown_stop_activated:
                        session_drawdown = (current_total_value - self.session_peak_value) / self.session_peak_value if self.session_peak_value > 0 else 0
                        if session_drawdown < self.SESSION_MAX_DRAWDOWN:
                            self.last_event_message = f"CIRCUIT BREAKER! Drawdown de {session_drawdown:.2%}"
                            logger.critical(self.last_event_message)
                            self.session_drawdown_stop_activated = True
                            if self.in_trade_position: self._execute_sell(current_price, "Circuit Breaker")

                if self.session_drawdown_stop_activated:
                    logger.warning("Circuit Breaker ATIVO. Novas operações suspensas.")
                    time.sleep(300); continue
                
                if self.in_trade_position:
                    self._manage_active_position(latest_data)
                else:
                    trade_signal_found = self._check_for_entry_signal(latest_data)
                    if not trade_signal_found: self._handle_dca_opportunity(latest_data)

                trade_stats = { 'trades': self.session_trades, 'wins': self.session_wins, 'total_pnl': self.session_total_pnl_usdt }
                display_trading_dashboard(self.portfolio, trade_stats, regime, self.last_event_message)
                self._save_state()
                time.sleep(60)
            except KeyboardInterrupt: self.graceful_shutdown(None, None)
            except Exception as e:
                logger.error(f"Erro inesperado no loop: {e}", exc_info=True); time.sleep(60)

    def _manage_active_position(self, latest_data: pd.Series):
        price = latest_data['close']
        self.highest_price_in_trade = max(self.highest_price_in_trade, price)
        pnl_pct = (price / self.buy_price - 1) if self.buy_price > 0 else 0
        pnl_usdt = (price - self.buy_price) * self.portfolio.trading_btc_balance
        self.last_event_message = f"Em trade. P&L: {pnl_pct:+.2%} (${pnl_usdt:,.2f})"

        if price <= self.current_stop_price:
            self._execute_sell(price, f"Stop Loss ({pnl_pct:.2%})"); return
        
        params = self.last_used_params
        if self.position_phase == 'INITIAL' and price >= self.buy_price * (1 + params.get('profit_threshold', 0.01) / 2):
            self.position_phase = 'TRAILING'
            new_stop = self.buy_price * (1 + (FEE_RATE + SLIPPAGE_RATE) * 2) # Breakeven + custos
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
        regime = latest_data['market_regime']
        specialist_model = self.models.get(regime)
        if not specialist_model:
            self.last_event_message = f"Aguardando (sem especialista para {regime})."
            return False
        
        if latest_data.get('vix_close_change', 0) > 0.10:
            self.last_event_message = f"Filtro VIX ativo ({latest_data['vix_close_change']:.2%})."
            return False

        if latest_data['volume'] < latest_data['volume_sma_50']:
            self.last_event_message = "Aguardando (volume baixo)."
            return False

        scaler, params = self.scalers.get(regime), self.strategy_params.get(regime)
        confidence_manager = self.confidence_managers.get(regime)
        features_for_prediction = pd.DataFrame([latest_data[self.model_feature_names]])
        scaled_features = scaler.transform(features_for_prediction)
        buy_confidence = specialist_model.predict_proba(scaled_features)[0][1]
        
        current_confidence_threshold = confidence_manager.get_confidence()
        self.last_event_message = f"Aguardando... Confiança do sinal: {buy_confidence:.2%} (necessário > {current_confidence_threshold:.2%})"

        if buy_confidence > current_confidence_threshold:
            base_risk = params.get('risk_per_trade_pct', 0.05)
            signal_strength = (buy_confidence - current_confidence_threshold) / (1.0 - current_confidence_threshold) if (1.0 - current_confidence_threshold) > 0 else 1.0
            aggression_exponent = params.get('aggression_exponent', 2.0); max_risk_scale = params.get('max_risk_scale', 3.0); min_risk_scale = params.get('min_risk_scale', 0.5)
            aggression_factor = min_risk_scale + (signal_strength ** aggression_exponent) * (max_risk_scale - min_risk_scale)
            trade_size_usdt = self.portfolio.trading_capital_usdt * (base_risk * aggression_factor)

            if trade_size_usdt < 10: return False
            
            stop_price = latest_data['close'] - (latest_data['atr'] * params.get('stop_loss_atr_multiplier', 2.5))
            self._execute_buy(latest_data['close'], trade_size_usdt, stop_price, buy_confidence, regime, params)
            return True
        return False

    def _handle_dca_opportunity(self, latest_data: pd.Series):
        if not DCA_IN_BEAR_MARKET_ENABLED: return

        if latest_data['market_regime'] in ['BEAR_CALMO', 'BEAR_VOLATIL']:
            now = datetime.now(timezone.utc)
            if self.last_dca_time and (now - self.last_dca_time) < timedelta(hours=24): return
            if self.portfolio.trading_capital_usdt < DCA_MIN_CAPITAL_USDT: return
            
            try:
                self.last_event_message = f"Executando DCA de ${DCA_DAILY_AMOUNT_USDT:,.2f}..."
                logger.info(self.last_event_message)
                
                if not self.client or USE_TESTNET:
                    qty_bought = DCA_DAILY_AMOUNT_USDT / latest_data['close']
                    cost = DCA_DAILY_AMOUNT_USDT * (1 + FEE_RATE)
                    buy_price_eff = latest_data['close'] * (1 + SLIPPAGE_RATE)
                else:
                    order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=round(DCA_DAILY_AMOUNT_USDT, 2))
                    qty_bought = float(order['executedQty']); cost = float(order['cummulativeQuoteQty'])
                    buy_price_eff = cost / qty_bought if qty_bought > 0 else 0
                
                self.portfolio.update_on_dca(qty_bought, cost)
                self.last_dca_time = now
                self._log_trade("DCA", buy_price_eff, qty_bought, "Acumulação em regime de baixa", 0, 0)
            except Exception as e:
                self.last_event_message = "Falha na compra de DCA."
                logger.error(f"ERRO AO EXECUTAR COMPRA DE DCA: {e}", exc_info=True)

    def _execute_buy(self, price, trade_size_usdt, stop_price, confidence, regime, params: dict):
        try:
            self.last_event_message = f"COMPRANDO ${trade_size_usdt:,.2f} (Conf. {confidence:.1%})"
            logger.info(self.last_event_message)
            
            if not self.client or USE_TESTNET:
                self.buy_price = price * (1 + SLIPPAGE_RATE)
                qty = trade_size_usdt / self.buy_price
                cost = trade_size_usdt
                self.portfolio.update_on_buy(qty, cost)
                self._log_trade("BUY (SIM)", self.buy_price, qty, f"Sinal ML ({confidence:.2%})")
            else:
                order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=round(trade_size_usdt, 2))
                self.buy_price = float(order['fills'][0]['price'])
                qty = float(order['executedQty']); cost = float(order['cummulativeQuoteQty'])
                self.portfolio.update_on_buy(qty, cost)
                self._log_trade("BUY (REAL)", self.buy_price, qty, f"Sinal ML ({confidence:.2%})")
            
            self.in_trade_position = True; self.position_phase = 'INITIAL'
            self.current_stop_price = stop_price; self.highest_price_in_trade = self.buy_price
            self.last_used_params = {**params, 'entry_regime': regime}
        except Exception as e:
            self.last_event_message = "Falha na execução da compra."
            logger.error(f"ERRO AO EXECUTAR COMPRA: {e}", exc_info=True)
            self.in_trade_position = False

    def _execute_sell(self, price, reason, partial=False, amount_to_sell=None):
        if amount_to_sell is None: amount_to_sell = self.portfolio.trading_btc_balance
        if amount_to_sell <= 0: return

        try:
            self.last_event_message = f"VENDENDO. Motivo: {reason}"
            logger.info(self.last_event_message)

            if not self.client or USE_TESTNET:
                actual_sell_price = price * (1 - SLIPPAGE_RATE)
                revenue = actual_sell_price * amount_to_sell
                buy_cost = self.buy_price * amount_to_sell
                pnl_usdt = (revenue * (1 - FEE_RATE)) - (buy_cost * (1 + FEE_RATE))
            else:
                order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=round(amount_to_sell, 5))
                actual_sell_price = float(order['fills'][0]['price'])
                revenue = float(order['cummulativeQuoteQty'])
                pnl_usdt = (actual_sell_price - self.buy_price) * amount_to_sell

            pnl_pct = (actual_sell_price / self.buy_price - 1) if self.buy_price > 0 else 0
            self.session_trades += 1
            self.session_total_pnl_usdt += pnl_usdt
            if pnl_usdt > 0: self.session_wins += 1

            entry_regime = self.last_used_params.get('entry_regime', 'N/A')
            if entry_regime in self.confidence_managers: self.confidence_managers[entry_regime].update(pnl_pct)

            self.portfolio.update_on_sell(amount_to_sell, revenue, pnl_usdt, actual_sell_price, self.last_used_params)
            self._log_trade("SELL (SIM)" if USE_TESTNET else "SELL (REAL)", actual_sell_price, amount_to_sell, reason, pnl_usdt, pnl_pct)
            
            if not partial: self.in_trade_position = False; self.position_phase = None; self.last_used_params = {}
        except Exception as e:
            self.last_event_message = "Falha na execução da venda."
            logger.error(f"ERRO AO EXECUTAR VENDA: {e}", exc_info=True)

    def _initialize_trade_log(self):
        if not os.path.exists(TRADES_LOG_FILE):
            with open(TRADES_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f); writer.writerow(['timestamp', 'type', 'price', 'quantity', 'pnl_usdt', 'pnl_percent', 'reason'])

    def _log_trade(self, trade_type, price, qty, reason, pnl_usdt=0, pnl_pct=0):
        with open(TRADES_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f); writer.writerow([datetime.now(timezone.utc).isoformat(), trade_type, price, qty, pnl_usdt, pnl_pct, reason])

    def _save_state(self):
        state = {
            'in_trade_position': self.in_trade_position, 'buy_price': self.buy_price,
            'position_phase': self.position_phase, 'current_stop_price': self.current_stop_price,
            'highest_price_in_trade': self.highest_price_in_trade, 'last_used_params': self.last_used_params,
            'portfolio': {'trading_capital_usdt': self.portfolio.trading_capital_usdt, 'trading_btc_balance': self.portfolio.trading_btc_balance, 'long_term_btc_holdings': self.portfolio.long_term_btc_holdings, 'initial_total_value_usdt': self.portfolio.initial_total_value_usdt,},
            'session_peak_value': self.session_peak_value, 'session_drawdown_stop_activated': self.session_drawdown_stop_activated,
            'session_trades': self.session_trades, 'session_wins': self.session_wins,
            'session_total_pnl_usdt': self.session_total_pnl_usdt,
            'last_dca_time': self.last_dca_time.isoformat() if self.last_dca_time else None
        }
        with open(BOT_STATE_FILE, 'w') as f: json.dump(state, f, indent=4)

    def _load_state(self):
        if not os.path.exists(BOT_STATE_FILE): return False
        try:
            with open(BOT_STATE_FILE, 'r') as f: state = json.load(f)
            self.in_trade_position = state.get('in_trade_position', False)
            self.buy_price = state.get('buy_price', 0.0)
            self.position_phase = state.get('position_phase')
            self.current_stop_price = state.get('current_stop_price', 0.0)
            self.highest_price_in_trade = state.get('highest_price_in_trade', 0.0)
            self.last_used_params = state.get('last_used_params', {})
            portfolio_state = state.get('portfolio', {})
            self.portfolio.trading_capital_usdt = portfolio_state.get('trading_capital_usdt', 0.0)
            self.portfolio.trading_btc_balance = portfolio_state.get('trading_btc_balance', 0.0)
            self.portfolio.long_term_btc_holdings = portfolio_state.get('long_term_btc_holdings', 0.0)
            self.portfolio.initial_total_value_usdt = portfolio_state.get('initial_total_value_usdt', 1.0)
            self.session_peak_value = state.get('session_peak_value', 0.0)
            self.session_drawdown_stop_activated = state.get('session_drawdown_stop_activated', False)
            self.session_trades = state.get('session_trades', 0)
            self.session_wins = state.get('session_wins', 0)
            self.session_total_pnl_usdt = state.get('session_total_pnl_usdt', 0.0)
            last_dca_time_str = state.get('last_dca_time')
            self.last_dca_time = datetime.fromisoformat(last_dca_time_str) if last_dca_time_str else None
            self.portfolio.session_peak_value = self.session_peak_value
            logger.info("✅ Estado anterior do bot e portfólio carregado com sucesso.")
            return True
        except Exception as e:
            logger.error(f"Não foi possível carregar o estado anterior: {e}. Iniciando com um estado limpo.")
            if os.path.exists(BOT_STATE_FILE): os.remove(BOT_STATE_FILE)
            return False

    def graceful_shutdown(self, signum, frame):
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO DE FORMA SEGURA... 🚨")
        self._save_state()
        logger.info("Estado do bot salvo. Desligando.")
        sys.exit(0)