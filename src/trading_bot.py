# src/trading_bot.py (VERSÃO 5.2 - FINAL CORRIGIDO)

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

# Importa o logger e a função de tabela centralizada
from src.logger import logger, log_table
from src.config import (
    API_KEY, API_SECRET, USE_TESTNET, SYMBOL, DATA_DIR, TRADES_LOG_FILE,
    BOT_STATE_FILE, MAX_USDT_ALLOCATION, FEE_RATE, SLIPPAGE_RATE,
    MODEL_METADATA_FILE
)
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
from src.confidence_manager import AdaptiveConfidenceManager

class PortfolioManager:
    """Gerencia todo o capital, posições e a tesouraria de longo prazo."""
    def __init__(self, client):
        self.client = client
        self.max_usdt_allocation = MAX_USDT_ALLOCATION
        self.trading_capital_usdt = 0.0
        self.trading_btc_balance = 0.0
        self.long_term_btc_holdings = 0.0
        self.initial_total_value_usdt = 0.0
        self.session_pnl_usdt = 0.0

    def sync_with_live_balance(self):
        if not self.client:
            logger.error("Cliente Binance indisponível para sincronização de saldo.")
            return False
        try:
            logger.info("📡 Sincronizando com o saldo real da conta Binance...")
            account_info = self.client.get_account()
            usdt_balance_obj = next((item for item in account_info['balances'] if item['asset'] == 'USDT'), {'free': '0'})
            btc_symbol = SYMBOL.replace("USDT", "")
            btc_balance_obj = next((item for item in account_info['balances'] if item['asset'] == btc_symbol), {'free': '0'})
            
            self.long_term_btc_holdings = float(btc_balance_obj['free'])
            self.trading_capital_usdt = min(float(usdt_balance_obj['free']), self.max_usdt_allocation)
            self.trading_btc_balance = 0.0

            current_price = self.get_current_price()
            if current_price is None: return False

            self.initial_total_value_usdt = self.get_total_portfolio_value_usdt(current_price)
            logger.info("✅ Portfólio Sincronizado com Saldo Real.")
            self.log_portfolio_status(current_price, "STATUS INICIAL DA SESSÃO")
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

    def update_on_buy(self, bought_btc_amount, cost_usdt, price):
        self.trading_capital_usdt -= cost_usdt
        self.trading_btc_balance += bought_btc_amount
        self.log_portfolio_status(price, "COMPRA EXECUTADA")

    def update_on_sell(self, sold_btc_amount, revenue_usdt, profit_usdt, price, params):
        self.trading_btc_balance -= sold_btc_amount
        
        if profit_usdt > 0:
            treasury_allocation = params.get('treasury_allocation_pct', 0.20)
            treasury_usdt = profit_usdt * treasury_allocation
            reinvestment_usdt = revenue_usdt - treasury_usdt
            self.trading_capital_usdt += reinvestment_usdt
            
            treasury_btc = treasury_usdt / price
            self.long_term_btc_holdings += treasury_btc
            logger.info(f"💰 Lucro de ${profit_usdt:,.2f} realizado! Alocando ${treasury_usdt:,.2f} ({treasury_btc:.8f} BTC) para a Tesouraria.")
        else:
            self.trading_capital_usdt += revenue_usdt
        
        self.log_portfolio_status(price, "VENDA EXECUTADA")

    def get_total_portfolio_value_usdt(self, current_btc_price):
        if current_btc_price is None or current_btc_price <= 0:
            return self.trading_capital_usdt
        
        trading_value = self.trading_capital_usdt + (self.trading_btc_balance * current_btc_price)
        holding_value = self.long_term_btc_holdings * current_btc_price
        return trading_value + holding_value

    def log_portfolio_status(self, current_btc_price, event_title="STATUS ATUAL"):
        if current_btc_price is None or current_btc_price <= 0: return

        total_value = self.get_total_portfolio_value_usdt(current_btc_price)
        self.session_pnl_usdt = total_value - self.initial_total_value_usdt
        pnl_color = "🟢" if self.session_pnl_usdt >= 0 else "🔴"
        pnl_display = f"{pnl_color} ${self.session_pnl_usdt:,.2f}"

        status_data = [
            ["Capital de Trading (USDT)", f"${self.trading_capital_usdt:,.2f}"],
            ["Posição de Trading (BTC)", f"{self.trading_btc_balance:.8f}"],
            [" ├─ Valor da Posição", f"${(self.trading_btc_balance * current_btc_price):,.2f}"],
            ["Tesouro de Longo Prazo (BTC)", f"{self.long_term_btc_holdings:.8f}"],
            [" └─ Valor do Tesouro", f"${(self.long_term_btc_holdings * current_btc_price):,.2f}"]
        ]
        summary_data = [
            ["Valor Total do Portfólio", f"💎 ${total_value:,.2f}"],
            ["Resultado da Sessão", pnl_display]
        ]
        
        log_table(f"📊 PORTFÓLIO: {event_title}", status_data, headers=["Ativo", "Valor"])
        log_table("Resumo Financeiro", summary_data, headers=["Métrica", "Valor"])

class TradingBot:
    def __init__(self):
        self.data_manager = DataManager()
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
        
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def load_all_specialists(self):
        try:
            with open(MODEL_METADATA_FILE, 'r') as f:
                metadata = json.load(f)
            self.model_feature_names = metadata.get('feature_names', [])
            summary = metadata.get('optimization_summary', {})
            
            if not self.model_feature_names: raise ValueError("Lista de features não encontrada nos metadados.")
            logger.info(f"✅ Metadados carregados. {len(self.model_feature_names)} features esperadas.")

            for regime, details in summary.items():
                if details.get('status') == 'Optimized and Saved':
                    try:
                        model_path = os.path.join(DATA_DIR, details['model_file'])
                        scaler_path = os.path.join(DATA_DIR, details['model_file'].replace('trading_model', 'scaler'))
                        params_path = os.path.join(DATA_DIR, details['params_file'])

                        self.models[regime] = joblib.load(model_path)
                        self.scalers[regime] = joblib.load(scaler_path)
                        with open(params_path, 'r') as f:
                            params = json.load(f)
                            self.strategy_params[regime] = params
                        
                        self.confidence_managers[regime] = AdaptiveConfidenceManager(
                            initial_confidence=params.get('initial_confidence', 0.6),
                            learning_rate=params.get('confidence_learning_rate', 0.05),
                            window_size=params.get('confidence_window_size', 5)
                        )
                        logger.info(f"-> Especialista para o regime '{regime}' carregado com sucesso.")
                    except Exception as e:
                        logger.error(f"-> Falha ao carregar especialista para o regime '{regime}': {e}")
                        
            if not self.models:
                logger.error("Nenhum modelo especialista foi carregado. O bot não pode operar.")
                return False
            return True
        except FileNotFoundError:
            logger.error(f"ERRO: Arquivo de metadados '{MODEL_METADATA_FILE}' não encontrado. Execute 'optimize' primeiro.")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado ao carregar especialistas: {e}", exc_info=True)
            return False

    def run(self):
        if not self.client:
            logger.error("Cliente Binance não inicializado. Encerrando.")
            return
        if not self.load_all_specialists():
            return
        
        self._initialize_trade_log()
        
        if not self._load_state():
            if not self.portfolio.sync_with_live_balance():
                logger.error("Falha fatal ao inicializar portfólio. Encerrando.")
                return
        
        logger.info("\n" + "="*60 + "\n🤖 >>> INICIANDO LOOP DE TRADING COM ESPECIALISTAS <<< 🤖\n" + "="*60)

        while True:
            try:
                features_df = self.data_manager.update_and_load_data(SYMBOL, '1m')
                if features_df.empty or len(features_df) < 300:
                    logger.warning("Dados insuficientes para calcular features. Aguardando...")
                    time.sleep(60)
                    continue

                current_price = features_df['close'].iloc[-1]
                regime = features_df['market_regime'].iloc[-1]
                
                if self.in_trade_position:
                    self._manage_active_position(current_price, self.last_used_params)
                else:
                    self.portfolio.log_portfolio_status(current_price, f"AGUARDANDO SINAL (Regime: {regime})")
                    
                    specialist_model = self.models.get(regime)
                    specialist_scaler = self.scalers.get(regime)
                    specialist_params = self.strategy_params.get(regime)
                    specialist_confidence = self.confidence_managers.get(regime)

                    if all([specialist_model, specialist_scaler, specialist_params, specialist_confidence]):
                        self._check_for_entry_signal(features_df, specialist_model, specialist_scaler, specialist_params, specialist_confidence)
                    else:
                        logger.info(f"Nenhum especialista de trading disponível para o regime '{regime}'. Aguardando...")

                self._save_state()
                time.sleep(60)
            except KeyboardInterrupt:
                self.graceful_shutdown(None, None)
            except Exception as e:
                logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
                time.sleep(60)

    def _manage_active_position(self, price: float, params: dict):
        self.highest_price_in_trade = max(self.highest_price_in_trade, price)

        pnl_pct = (price / self.buy_price) - 1 if self.buy_price > 0 else 0.0
        pnl_color = "🟢" if pnl_pct >= 0 else "🔴"
        trade_status_data = [
            ["Fase da Posição", self.position_phase],
            ["Preço de Compra", f"${self.buy_price:,.2f}"],
            ["Preço Atual", f"${price:,.2f}"],
            ["Preço Máximo Atingido", f"${self.highest_price_in_trade:,.2f}"],
            ["Stop Loss Atual", f"🛑 ${self.current_stop_price:,.2f}"],
            ["Resultado Atual", f"{pnl_color} {pnl_pct:+.2%}"]
        ]
        log_table("🛡️ TRADE ATIVO", trade_status_data, headers=["Métrica", "Valor"])

        if price <= self.current_stop_price:
            logger.info(f"🔴 STOP LOSS ATINGIDO a ${price:,.2f} (Stop era ${self.current_stop_price:,.2f})")
            self._execute_sell(price, f"Stop Loss ({pnl_pct:.2%})")
            return

        if self.position_phase == 'INITIAL':
            if price >= self.buy_price * (1 + params.get('stop_loss_threshold', 0.02)):
                self.position_phase = 'BREAKEVEN'
                self.current_stop_price = self.buy_price * (1 + (FEE_RATE * 2))
                logger.info(f"✅ POSIÇÃO SEGURA! Stop movido para Breakeven em ${self.current_stop_price:,.2f}")
        
        elif self.position_phase == 'BREAKEVEN':
            if price >= self.buy_price * (1 + params.get('profit_threshold', 0.04)):
                logger.info(f"💰 REALIZAÇÃO PARCIAL! Preço atingiu alvo de {params.get('profit_threshold', 0.04):.2%}")
                amount_to_sell = self.portfolio.trading_btc_balance * params.get('partial_sell_pct', 0.5)
                self._execute_sell(price, "Realização Parcial de Lucro", partial=True, amount_to_sell=amount_to_sell)
                self.position_phase = 'TRAILING'
        
        elif self.position_phase == 'TRAILING':
            trailing_stop_pct = params.get('stop_loss_threshold', 0.02) * params.get('trailing_stop_multiplier', 1.5)
            new_trailing_stop = self.highest_price_in_trade * (1 - trailing_stop_pct)
            if new_trailing_stop > self.current_stop_price:
                self.current_stop_price = new_trailing_stop
                logger.info(f"📈 TRAILING STOP ATUALIZADO para ${self.current_stop_price:,.2f}")

    def _check_for_entry_signal(self, features_df: pd.DataFrame, model, scaler, params: dict, confidence_manager: AdaptiveConfidenceManager):
        regime = features_df['market_regime'].iloc[-1]
        if regime == 'BEAR':
            logger.info(f"🐻 Regime 'BEAR' detectado. Trades de compra estão temporariamente bloqueados.")
            return

        current_price = features_df['close'].iloc[-1]
        
        trainer = ModelTrainer()
        processed_df, _ = trainer._prepare_features(features_df.copy())
        
        if not all(f in processed_df.columns for f in self.model_feature_names):
             logger.warning("Nem todas as features necessárias estão presentes nos dados recentes. Pulando predição.")
             return
        
        features_for_prediction = processed_df.tail(1)[self.model_feature_names]
        
        scaled_features = scaler.transform(features_for_prediction)
        buy_confidence = model.predict_proba(scaled_features)[0][1]
        current_confidence_threshold = confidence_manager.get_confidence()

        log_table("🧠 ANÁLISE DE SINAL", [
            ["Preço Atual", f"${current_price:,.2f}"],
            ["Regime de Mercado", f"{regime}"],
            ["Confiança do Modelo (Comprar)", f"{buy_confidence:.2%}"],
            ["Limiar de Confiança (Dinâmico)", f"{current_confidence_threshold:.2%}"],
            ["Decisão", f"{'🟢 COMPRAR' if buy_confidence > current_confidence_threshold else '🔴 AGUARDAR'}"]
        ], headers=["Métrica", "Valor"])
        
        if buy_confidence > current_confidence_threshold:
            signal_strength = (buy_confidence - current_confidence_threshold) / (1.0 - current_confidence_threshold)
            
            base_risk = params.get('risk_per_trade_pct', 0.05)
            if regime == 'RECUPERACAO': base_risk /= 2
            elif regime == 'LATERAL': base_risk /= 4
            dynamic_risk_pct = base_risk * (0.5 + signal_strength)
            trade_size_usdt = self.portfolio.trading_capital_usdt * dynamic_risk_pct
            
            logger.info(f"🎯 SINAL DE COMPRA CONFIRMADO! Risco dinâmico ({regime}): {dynamic_risk_pct:.2%}. Planejando trade de ~${trade_size_usdt:,.2f}.")
            
            if self.portfolio.trading_capital_usdt < 10:
                logger.warning(f"Sinal ignorado. Capital ({self.portfolio.trading_capital_usdt:.2f}) abaixo do mínimo.")
                return
            if trade_size_usdt < 10:
                logger.warning(f"Sinal ignorado. Valor do trade ({trade_size_usdt:.2f}) abaixo do mínimo.")
                return

            self._execute_buy(current_price, trade_size_usdt, buy_confidence, regime, params)

    def _execute_buy(self, price, trade_size_usdt, confidence, regime, params: dict):
        try:
            buy_price_expected = price * (1 + SLIPPAGE_RATE)
            quantity_to_buy = trade_size_usdt / buy_price_expected
            logger.info(f"EXECUTANDO ORDEM DE COMPRA: {quantity_to_buy:.8f} BTC a ~${price:,.2f}")

            if USE_TESTNET:
                 order = self.client.create_test_order(symbol=SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quantity=f"{quantity_to_buy:.8f}")
            else:
                 order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quantity=f"{quantity_to_buy:.8f}")
            logger.info(f"Ordem de compra enviada: {order}")
            
            buy_price_filled = buy_price_expected 
            bought_qty = quantity_to_buy
            cost = buy_price_filled * bought_qty

            self.buy_price = buy_price_filled
            self.in_trade_position = True
            self.position_phase = 'INITIAL'
            self.current_stop_price = self.buy_price * (1 - params.get('stop_loss_threshold', 0.02))
            self.highest_price_in_trade = self.buy_price
            self.last_used_params = {**params, 'entry_regime': regime}
            
            self.portfolio.update_on_buy(bought_qty, cost, buy_price_filled)
            self._log_trade("BUY", buy_price_filled, bought_qty, f"Sinal do ML ({confidence:.2%})", 0, 0)
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            logger.error(f"ERRO AO EXECUTAR COMPRA: {e}", exc_info=True)
            self.in_trade_position = False

    def _execute_sell(self, price, reason, partial=False, amount_to_sell=None):
        if amount_to_sell is None: amount_to_sell = self.portfolio.trading_btc_balance
        if amount_to_sell <= 0: return

        try:
            logger.info(f"EXECUTANDO ORDEM DE VENDA: {amount_to_sell:.8f} BTC a ~${price:,.2f} | Motivo: {reason}")
            sell_price_expected = price * (1 - SLIPPAGE_RATE)

            if USE_TESTNET:
                order = self.client.create_test_order(symbol=SYMBOL, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=f"{amount_to_sell:.8f}")
            else:
                order = self.client.create_order(symbol=SYMBOL, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=f"{amount_to_sell:.8f}")
            logger.info(f"Ordem de venda enviada: {order}")

            sell_price_filled = sell_price_expected
            sold_qty = amount_to_sell
            revenue = sell_price_filled * sold_qty
            
            pnl_usdt = (sell_price_filled - self.buy_price) * sold_qty
            pnl_pct = (sell_price_filled / self.buy_price) - 1 if self.buy_price > 0 else 0
            
            entry_regime = self.last_used_params.get('entry_regime', 'LATERAL')
            confidence_manager = self.confidence_managers.get(entry_regime, list(self.confidence_managers.values())[0])

            self.portfolio.update_on_sell(sold_qty, revenue, pnl_usdt, sell_price_filled, self.last_used_params)
            confidence_manager.update(pnl_pct)
            self._log_trade("SELL", sell_price_filled, sold_qty, reason, pnl_usdt, pnl_pct)
            
            if not partial:
                self.in_trade_position = False
                self.position_phase = None
                self.last_used_params = {}
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            logger.error(f"ERRO AO EXECUTAR VENDA: {e}", exc_info=True)

    def _initialize_trade_log(self):
        if not os.path.exists(TRADES_LOG_FILE):
            with open(TRADES_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'type', 'price', 'quantity', 'pnl_usdt', 'pnl_percent', 'reason'])

    def _log_trade(self, trade_type, price, qty, reason, pnl_usdt=0, pnl_pct=0):
        with open(TRADES_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([pd.Timestamp.now(tz='UTC').isoformat(), trade_type, price, qty, pnl_usdt, pnl_pct, reason])

    def _save_state(self):
        state = {
            'in_trade_position': self.in_trade_position,
            'buy_price': self.buy_price,
            'position_phase': self.position_phase,
            'current_stop_price': self.current_stop_price,
            'highest_price_in_trade': self.highest_price_in_trade,
            'last_used_params': self.last_used_params,
            'portfolio': self.portfolio.__dict__
        }
        with open(BOT_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)

    def _load_state(self):
        if not os.path.exists(BOT_STATE_FILE): return False
        try:
            with open(BOT_STATE_FILE, 'r') as f:
                state = json.load(f)
            
            self.in_trade_position = state.get('in_trade_position', False)
            self.buy_price = state.get('buy_price', 0.0)
            self.position_phase = state.get('position_phase')
            self.current_stop_price = state.get('current_stop_price', 0.0)
            self.highest_price_in_trade = state.get('highest_price_in_trade', 0.0)
            self.last_used_params = state.get('last_used_params', {})
            
            portfolio_state = state.get('portfolio', {})
            self.portfolio.trading_capital_usdt = portfolio_state.get('trading_capital_usdt', self.portfolio.max_usdt_allocation)
            self.portfolio.trading_btc_balance = portfolio_state.get('trading_btc_balance', 0.0)
            self.portfolio.long_term_btc_holdings = portfolio_state.get('long_term_btc_holdings', 0.0)
            self.portfolio.initial_total_value_usdt = portfolio_state.get('initial_total_value_usdt', 0.0)
            
            logger.info("✅ Estado anterior do bot e portfólio carregado com sucesso.")
            current_price = self.portfolio.get_current_price()
            if current_price:
                self.portfolio.log_portfolio_status(current_price, "STATUS RESTAURADO")
            return True
        except Exception as e:
            logger.error(f"Não foi possível carregar o estado anterior: {e}. Iniciando com um estado limpo.")
            if os.path.exists(BOT_STATE_FILE):
                os.remove(BOT_STATE_FILE)
            return False

    def graceful_shutdown(self, signum, frame):
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO DE FORMA SEGURA... 🚨")
        self._save_state()
        logger.info("Estado do bot salvo. Desligando.")
        sys.exit(0)