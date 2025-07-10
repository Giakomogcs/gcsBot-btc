# src/trading_bot.py (VERSÃO 8.4 - Final, Completa e Corrigida)

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
    API_KEY, API_SECRET, USE_TESTNET, SYMBOL, DATA_DIR, TRADES_LOG_FILE, BOT_STATE_FILE,
    MAX_USDT_ALLOCATION, FEE_RATE, SLIPPAGE_RATE, IOF_RATE,
    MODEL_METADATA_FILE, DCA_IN_BEAR_MARKET_ENABLED, DCA_DAILY_AMOUNT_USDT, DCA_MIN_CAPITAL_USDT
)
from src.data_manager import DataManager
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
        self.initial_total_value_usdt = 1.0
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

class TradingBot:
    def __init__(self):
        self.data_manager = DataManager()
        self.client = self.data_manager.client
        self.portfolio = PortfolioManager(self.client)
        self.models, self.scalers, self.strategy_params = {}, {}, {}
        self.confidence_managers = {}
        self.regime_map = {}
        self.model_feature_names = []
        self.in_trade_position = False
        self.buy_price = 0.0
        self.position_phase = None
        self.current_stop_price = 0.0
        self.highest_price_in_trade = 0.0
        self.last_used_params = {}
        self.session_peak_value = 0.0
        self.session_trades, self.session_wins, self.session_total_pnl_usdt = 0, 0, 0.0
        self.session_drawdown_stop_activated = False
        self.SESSION_MAX_DRAWDOWN = -0.15
        self.last_dca_time = None
        self.last_event_message = "Inicializando o bot..."
        self.specialist_stats = {}
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def _load_all_specialists(self):
        try:
            with open(MODEL_METADATA_FILE, 'r') as f: metadata = json.load(f)
            logger.info("✅ Metadados carregados. Verificando validade do modelo...")
            valid_until_dt = datetime.fromisoformat(metadata['valid_until'])
            if datetime.now(timezone.utc) > valid_until_dt:
                logger.error(f"🚨 ERRO CRÍTICO: O CONJUNTO DE MODELOS EXPIROU EM {valid_until_dt.strftime('%Y-%m-%d')}! 🚨")
                return False
            
            self.model_feature_names = metadata['feature_names']
            summary = metadata.get('optimization_summary', {})
            
            loaded_specialists_count = 0
            for regime, result in summary.items():
                specialist_to_load = regime
                if result.get('status') == 'Fallback to Generalist':
                    specialist_to_load = result['fallback_model']
                
                self.regime_map[regime] = specialist_to_load
                
                if specialist_to_load and specialist_to_load not in self.models:
                    try:
                        final_spec_info = summary.get(specialist_to_load, {})
                        if final_spec_info.get('status') == 'Optimized and Saved':
                            self.models[specialist_to_load] = joblib.load(os.path.join(DATA_DIR, final_spec_info['model_file']))
                            self.scalers[specialist_to_load] = joblib.load(os.path.join(DATA_DIR, final_spec_info['scaler_file']))
                            with open(os.path.join(DATA_DIR, final_spec_info['params_file']), 'r') as p:
                                self.strategy_params[specialist_to_load] = json.load(p)
                            loaded_specialists_count += 1
                    except Exception as e:
                        logger.error(f"Falha ao carregar artefatos para '{specialist_to_load}': {e}")
            
            if not self.models:
                logger.error("ERRO CRÍTICO: Nenhum especialista foi carregado. Execute a otimização.")
                return False
            logger.info(f"✅ {loaded_specialists_count} especialista(s) únicos carregados e prontos para operar.")
            return True
        except Exception as e:
            logger.error(f"Erro fatal ao carregar especialistas: {e}", exc_info=True)
            return False

    def _get_active_specialist(self, regime: str):
        specialist_name = self.regime_map.get(regime)
        if not specialist_name: return None, None, None, None
        model = self.models.get(specialist_name)
        scaler = self.scalers.get(specialist_name)
        params = self.strategy_params.get(specialist_name)
        if specialist_name not in self.confidence_managers:
            confidence_params = {
                'initial_confidence': params.get('initial_confidence', 0.7),
                'learning_rate': params.get('confidence_learning_rate', 0.05),
                'window_size': params.get('confidence_window_size', 10),
                'pnl_clamp_value': params.get('confidence_pnl_clamp', 0.02)
            }
            self.confidence_managers[specialist_name] = AdaptiveConfidenceManager(**confidence_params)
        confidence_manager = self.confidence_managers.get(specialist_name)
        return model, scaler, params, confidence_manager

    def run(self):
        if not self._load_all_specialists(): return
        self._initialize_trade_log()
        if not self._load_state():
            if not self.portfolio.sync_with_live_balance():
                logger.critical("Falha fatal ao inicializar portfólio. Encerrando."); return
            self.session_peak_value = self.portfolio.initial_total_value_usdt
        
        while True:
            try:
                processed_df = self.data_manager.update_and_load_data(SYMBOL, '1m')
                if processed_df.empty: time.sleep(60); continue
                latest_data = processed_df.iloc[-1]
                
                self._check_and_manage_drawdown(latest_data)
                if self.session_drawdown_stop_activated:
                    logger.warning("Circuit Breaker ATIVO. Novas operações suspensas."); time.sleep(300); continue
                
                if self.in_trade_position: self._manage_active_position(latest_data)
                else:
                    trade_signal_found = self._check_for_entry_signal(latest_data)
                    if not trade_signal_found: self._handle_dca_opportunity(latest_data)

                status_data = self._build_status_data(latest_data)
                display_trading_dashboard(status_data)
                self._save_state()
                time.sleep(60)
            except KeyboardInterrupt: self.graceful_shutdown(None, None)
            except Exception as e: logger.error(f"Erro inesperado no loop: {e}", exc_info=True); time.sleep(60)

    def _check_and_manage_drawdown(self, latest_data):
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
                if self.in_trade_position: self._execute_sell(current_price, "Circuit Breaker")

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
            new_stop = self.buy_price * (1 + (FEE_RATE + SLIPPAGE_RATE) * 2)
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
        model, scaler, params, confidence_manager = self._get_active_specialist(regime)

        if not all([model, scaler, params, confidence_manager]):
            self.last_event_message = f"Aguardando (sem especialista para {regime})."; return False
        
        if latest_data.get('volume', 0) < latest_data.get('volume_sma_50', 0):
            self.last_event_message = "Aguardando (volume baixo)."; return False

        features_for_prediction = pd.DataFrame([latest_data[self.model_feature_names]])
        scaled_features = scaler.transform(features_for_prediction)
        buy_confidence = model.predict_proba(scaled_features)[0][1]
        
        current_confidence_threshold = confidence_manager.get_confidence()
        self.last_event_message = f"Aguardando... Confiança: {buy_confidence:.2%} (Alvo: {current_confidence_threshold:.2%})"

        if buy_confidence > current_confidence_threshold:
            base_risk = params.get('risk_per_trade_pct', 0.05)
            signal_strength = (buy_confidence - current_confidence_threshold) / (1.0 - current_confidence_threshold) if (1.0 - current_confidence_threshold) > 0 else 1.0
            aggression_factor = params.get('min_risk_scale', 0.5) + (signal_strength ** params.get('aggression_exponent', 2.0)) * (params.get('max_risk_scale', 3.0) - params.get('min_risk_scale', 0.5))
            trade_size_usdt = self.portfolio.trading_capital_usdt * (base_risk * aggression_factor)

            if trade_size_usdt < 10: return False
            
            stop_price = latest_data['close'] - (latest_data['atr'] * params.get('stop_loss_atr_multiplier', 2.5))
            self._execute_buy(latest_data['close'], trade_size_usdt, stop_price, buy_confidence, regime, params)
            return True
        return False

    def _handle_dca_opportunity(self, latest_data: pd.Series):
        if not DCA_IN_BEAR_MARKET_ENABLED or 'BEAR' not in latest_data['market_regime']: return

        now = datetime.now(timezone.utc)
        if self.last_dca_time and (now - self.last_dca_time) < timedelta(hours=24): return
        if self.portfolio.trading_capital_usdt < DCA_MIN_CAPITAL_USDT: return
        
        try:
            self.last_event_message = f"Executando DCA de ${DCA_DAILY_AMOUNT_USDT:,.2f}..."
            logger.info(self.last_event_message)
            
            cost = DCA_DAILY_AMOUNT_USDT
            if not self.client or USE_TESTNET:
                buy_price_eff = latest_data['close'] * (1 + SLIPPAGE_RATE)
                qty_bought = cost / buy_price_eff
                cost_with_fees = cost * (1 + FEE_RATE)
                self._log_trade("DCA (SIM)", buy_price_eff, qty_bought, "Acumulação em baixa")
            else:
                order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=round(cost, 2))
                qty_bought, cost_with_fees = float(order['executedQty']), float(order['cummulativeQuoteQty'])
                buy_price_eff = cost_with_fees / qty_bought if qty_bought > 0 else latest_data['close']
                self._log_trade("DCA (REAL)", buy_price_eff, qty_bought, "Acumulação em baixa")
            
            self.portfolio.update_on_dca(qty_bought, cost_with_fees)
            self.last_dca_time = now
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
                cost = trade_size_usdt * (1 + FEE_RATE + IOF_RATE)
                self.portfolio.update_on_buy(qty, cost)
                self._log_trade("BUY (SIM)", self.buy_price, qty, f"Sinal ML ({confidence:.2%})")
            else:
                order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=round(trade_size_usdt, 2))
                self.buy_price = float(order['fills'][0]['price']) if order['fills'] else price
                qty, cost = float(order['executedQty']), float(order['cummulativeQuoteQty'])
                self.portfolio.update_on_buy(qty, cost)
                self._log_trade("BUY (REAL)", self.buy_price, qty, f"Sinal ML ({confidence:.2%})")
            
            self.in_trade_position, self.position_phase = True, 'INITIAL'
            self.current_stop_price, self.highest_price_in_trade = stop_price, self.buy_price
            # <<< MUDANÇA: Armazena o NOME do especialista que entrou no trade >>>
            self.last_used_params = {**params, 'entry_regime': regime, 'entry_specialist': self.regime_map.get(regime)}
        except Exception as e:
            logger.error(f"ERRO AO EXECUTAR COMPRA: {e}", exc_info=True)
            self.in_trade_position = False

    def _execute_sell(self, price, reason):
        amount_to_sell = self.portfolio.trading_btc_balance
        if amount_to_sell <= 0: return
        try:
            self.last_event_message = f"VENDENDO. Motivo: {reason}"
            logger.info(self.last_event_message)
            
            pnl_usdt, pnl_pct, actual_sell_price = 0, 0, price
            if not self.client or USE_TESTNET:
                actual_sell_price = price * (1 - SLIPPAGE_RATE)
                revenue = actual_sell_price * amount_to_sell
                buy_cost = self.buy_price * amount_to_sell
                pnl_usdt = (revenue * (1 - FEE_RATE)) - (buy_cost * (1 + FEE_RATE + IOF_RATE))
                pnl_pct = (actual_sell_price / self.buy_price - 1) if self.buy_price > 0 else 0
                self._log_trade("SELL (SIM)", actual_sell_price, amount_to_sell, reason, pnl_usdt, pnl_pct)
            else:
                order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=round(amount_to_sell, 5))
                actual_sell_price = float(order['fills'][0]['price']) if order['fills'] else price
                revenue = float(order['cummulativeQuoteQty'])
                pnl_usdt = revenue - (self.buy_price * amount_to_sell)
                pnl_pct = (actual_sell_price / self.buy_price - 1) if self.buy_price > 0 else 0
                self._log_trade("SELL (REAL)", actual_sell_price, amount_to_sell, reason, pnl_usdt, pnl_pct)

            self.session_trades += 1
            if pnl_usdt > 0: self.session_wins += 1
            self.session_total_pnl_usdt += pnl_usdt
            self.last_used_params['last_pnl_pct'] = pnl_pct

            specialist_name = self.last_used_params.get('entry_specialist')
            if specialist_name and specialist_name in self.confidence_managers:
                confidence_manager = self.confidence_managers[specialist_name]
                # <<< CORREÇÃO: Captura os valores ANTES e DEPOIS do update >>>
                confidence_before = confidence_manager.get_confidence()
                confidence_manager.update(pnl_pct)
                confidence_after = confidence_manager.get_confidence()
                
                log_payload = {
                    'event_type': 'TRADE_CLOSE', 'specialist': specialist_name, 'pnl_usd': pnl_usdt,
                    'pnl_pct': pnl_pct, 'reason': reason, 'buy_price': self.buy_price,
                    'sell_price': actual_sell_price, 'quantity_btc': amount_to_sell,
                    'confidence_threshold_before': confidence_before, 'confidence_threshold_after': confidence_after,
                }
                logger.performance("Trade fechado", extra_data=log_payload)
                self._update_specialist_stats(specialist_name, pnl_usdt)

            self.portfolio.update_on_sell(amount_to_sell, revenue, pnl_usdt, actual_sell_price, self.last_used_params)
            self.in_trade_position, self.position_phase = False, None
            # Mantemos o last_used_params para o display, ele será sobrescrito na próxima compra
        except Exception as e: logger.error(f"ERRO AO EXECUTAR VENDA: {e}", exc_info=True)

    def _initialize_trade_log(self):
        if not os.path.exists(TRADES_LOG_FILE):
            with open(TRADES_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(['timestamp', 'type', 'price', 'quantity', 'pnl_usdt', 'pnl_percent', 'reason'])

    def _log_trade(self, trade_type, price, qty, reason, pnl_usdt=0, pnl_pct=0):
        with open(TRADES_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(), trade_type, f"{price:.2f}", f"{qty:.8f}", f"{pnl_usdt:.4f}", f"{pnl_pct:.4%}", reason])

    def _update_specialist_stats(self, specialist_name, pnl_usdt):
        if not specialist_name: return
        if specialist_name not in self.specialist_stats:
            self.specialist_stats[specialist_name] = {'total_trades': 0, 'wins': 0, 'total_pnl': 0.0}
        
        stats = self.specialist_stats[specialist_name]
        stats['total_trades'] += 1
        stats['total_pnl'] += pnl_usdt
        if pnl_usdt > 0: stats['wins'] += 1

    def _build_status_data(self, latest_data: pd.Series) -> dict:
        current_price = latest_data['close']
        total_value = self.portfolio.get_total_portfolio_value_usdt(current_price)
        growth_pct = (total_value / self.portfolio.initial_total_value_usdt - 1) * 100 if self.portfolio.initial_total_value_usdt > 0 else 0
        regime = latest_data['market_regime']
        active_specialist_name = self.regime_map.get(regime)
        confidence_manager = self.confidence_managers.get(active_specialist_name)
        last_op_specialist_name = self.last_used_params.get('entry_specialist', 'N/A')

        return {
            "portfolio": { "current_price": current_price, "total_value_usdt": total_value, "session_growth_pct": growth_pct, "trading_capital_usdt": self.portfolio.trading_capital_usdt, "trading_btc_balance": self.portfolio.trading_btc_balance, "trading_btc_value_usdt": self.portfolio.trading_btc_balance * current_price, "long_term_btc_holdings": self.portfolio.long_term_btc_holdings, "long_term_value_usdt": self.portfolio.long_term_btc_holdings * current_price, },
            "session_stats": { "trades": self.session_trades, "wins": self.session_wins, "total_pnl_usdt": self.session_total_pnl_usdt, },
            "bot_status": { "market_regime": regime, "active_specialist": active_specialist_name, "confidence_threshold": confidence_manager.get_confidence() if confidence_manager else 0, "last_event_message": self.last_event_message, },
            "last_operation": { "specialist_name": last_op_specialist_name, "pnl_pct": self.last_used_params.get('last_pnl_pct', 0.0), **self.specialist_stats.get(last_op_specialist_name, {}) }
        }

    def _save_state(self):
        state = {
            'in_trade_position': self.in_trade_position, 'buy_price': self.buy_price, 'position_phase': self.position_phase,
            'current_stop_price': self.current_stop_price, 'highest_price_in_trade': self.highest_price_in_trade,
            'last_used_params': self.last_used_params, 'session_peak_value': self.session_peak_value,
            'session_drawdown_stop_activated': self.session_drawdown_stop_activated, 'session_trades': self.session_trades,
            'session_wins': self.session_wins, 'session_total_pnl_usdt': self.session_total_pnl_usdt,
            'last_dca_time': self.last_dca_time.isoformat() if self.last_dca_time else None,
            'specialist_stats': self.specialist_stats, # Salva as estatísticas
            'portfolio': { 'trading_capital_usdt': self.portfolio.trading_capital_usdt, 'trading_btc_balance': self.portfolio.trading_btc_balance, 'long_term_btc_holdings': self.portfolio.long_term_btc_holdings, 'initial_total_value_usdt': self.portfolio.initial_total_value_usdt,},
        }
        with open(BOT_STATE_FILE, 'w') as f: json.dump(state, f, indent=4)

    def _load_state(self):
        if not os.path.exists(BOT_STATE_FILE): return False
        try:
            with open(BOT_STATE_FILE, 'r') as f: state = json.load(f)
            self.in_trade_position = state.get('in_trade_position', False)
            self.buy_price, self.position_phase = state.get('buy_price', 0.0), state.get('position_phase')
            self.current_stop_price, self.highest_price_in_trade = state.get('current_stop_price', 0.0), state.get('highest_price_in_trade', 0.0)
            self.last_used_params, self.session_peak_value = state.get('last_used_params', {}), state.get('session_peak_value', 0.0)
            self.session_drawdown_stop_activated = state.get('session_drawdown_stop_activated', False)
            self.session_trades, self.session_wins, self.session_total_pnl_usdt = state.get('session_trades', 0), state.get('session_wins', 0), state.get('session_total_pnl_usdt', 0.0)
            last_dca_time_str = state.get('last_dca_time')
            self.last_dca_time = datetime.fromisoformat(last_dca_time_str) if last_dca_time_str else None
            self.specialist_stats = state.get('specialist_stats', {}) # Carrega as estatísticas
            portfolio_state = state.get('portfolio', {})
            self.portfolio.trading_capital_usdt, self.portfolio.trading_btc_balance, self.portfolio.long_term_btc_holdings, self.portfolio.initial_total_value_usdt = portfolio_state.get('trading_capital_usdt', 0.0), portfolio_state.get('trading_btc_balance', 0.0), portfolio_state.get('long_term_btc_holdings', 0.0), portfolio_state.get('initial_total_value_usdt', 1.0)
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