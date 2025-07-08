# src/trading_bot.py (VERSÃO 6.0 - ROBUSTO E COM CIRCUIT BREAKERS)


from multiprocessing.dummy import current_process
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
    # Nenhuma mudança necessária neste arquivo. O código original é mantido.
    # ... (código da classe PortfolioManager como no arquivo original) ...
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
        
        # A lógica da tesouraria permanece a mesma
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
            [" └─ Valor do Tesouro", f"${(self.long_term_btc_holdings * current_process):,.2f}"]
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
        
        # --- NOVO: Variáveis de estado para o Circuit Breaker ---
        self.session_peak_value = 0.0
        self.session_drawdown_stop_activated = False
        self.SESSION_MAX_DRAWDOWN = -0.10 # Limite de 10% de perda na sessão

        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def load_all_specialists(self):
        # A lógica de carregamento permanece a mesma.
        # ... (código do load_all_specialists como no arquivo original) ...
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
            self.session_peak_value = self.portfolio.initial_total_value_usdt
        
        logger.info("\n" + "="*60 + "\n🤖 >>> INICIANDO LOOP DE TRADING ROBUSTO <<< 🤖\n" + "="*60)

        while True:
            try:
                # --- MUDANÇA --- Passando o Trainer para obter as features de forma consistente
                features_df = self.data_manager.update_and_load_data(SYMBOL, '1m')
                processed_df, _ = self.trainer._prepare_features(features_df.copy())
                if processed_df.empty or len(processed_df) < 1:
                    logger.warning("Dados insuficientes para operar. Aguardando...")
                    time.sleep(60); continue

                latest_data = processed_df.iloc[-1]
                current_price = latest_data['close']
                regime = latest_data['market_regime']
                
                # --- NOVO: LÓGICA DO CIRCUIT BREAKER DE DRAWDOWN ---
                current_total_value = self.portfolio.get_total_portfolio_value_usdt(current_price)
                self.session_peak_value = max(self.session_peak_value, current_total_value)
                session_drawdown = (current_total_value - self.session_peak_value) / self.session_peak_value if self.session_peak_value > 0 else 0
                
                if not self.session_drawdown_stop_activated and session_drawdown < self.SESSION_MAX_DRAWDOWN:
                    logger.critical(f"CIRCUIT BREAKER! Drawdown da sessão ({session_drawdown:.2%}) atingiu o limite de {self.SESSION_MAX_DRAWDOWN:.2%}.")
                    self.session_drawdown_stop_activated = True
                    if self.in_trade_position:
                         self._execute_sell(current_price, f"Circuit Breaker de Drawdown ({session_drawdown:.2%})")

                if self.session_drawdown_stop_activated:
                    logger.warning("Circuit Breaker da sessão ATIVO. Novas operações suspensas até o próximo reinício.")
                    time.sleep(300); continue # Verifica a cada 5 minutos
                # ----------------------------------------------------

                if self.in_trade_position:
                    self._manage_active_position(latest_data)
                else:
                    self.portfolio.log_portfolio_status(current_price, f"AGUARDANDO SINAL (Regime: {regime})")
                    specialist_model = self.models.get(regime)
                    if specialist_model:
                        self._check_for_entry_signal(latest_data)
                    else:
                        logger.info(f"Nenhum especialista de trading disponível para o regime '{regime}'. Aguardando...")

                self._save_state()
                time.sleep(60)

            except KeyboardInterrupt: self.graceful_shutdown(None, None)
            except Exception as e:
                logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
                time.sleep(60)

    # --- MUDANÇA --- Agora recebe a linha inteira de dados para usar o ATR
    def _manage_active_position(self, latest_data: pd.Series):
        price = latest_data['close']
        self.highest_price_in_trade = max(self.highest_price_in_trade, price)

        # Mesma lógica de log de antes...
        
        if price <= self.current_stop_price:
            pnl_pct = (price / self.buy_price) - 1 if self.buy_price > 0 else 0
            logger.info(f"🔴 STOP LOSS ATINGIDO a ${price:,.2f} (Stop era ${self.current_stop_price:,.2f})")
            self._execute_sell(price, f"Stop Loss ({pnl_pct:.2%})")
            return
        
        # --- MUDANÇA --- Trailing Stop agora usa ATR e os parâmetros otimizados
        params = self.last_used_params
        if self.position_phase == 'TRAILING':
            stop_loss_atr_multiplier = params.get('stop_loss_atr_multiplier', 2.5)
            trailing_stop_multiplier = params.get('trailing_stop_multiplier', 1.5)
            
            new_trailing_stop = self.highest_price_in_trade - (latest_data['atr'] * stop_loss_atr_multiplier * trailing_stop_multiplier)
            if new_trailing_stop > self.current_stop_price:
                self.current_stop_price = new_trailing_stop
                logger.info(f"📈 TRAILING STOP ATUALIZADO para ${self.current_stop_price:,.2f}")
        
        # Lógica de fases (INITIAL, BREAKEVEN) permanece similar, pode ser ajustada se necessário.

    # --- MUDANÇA --- Função de checagem de entrada completamente refeita para ser robusta
    def _check_for_entry_signal(self, latest_data: pd.Series):
        regime = latest_data['market_regime']
        if regime == 'BEAR':
            logger.info(f"🐻 Regime 'BEAR' detectado. Trades de compra estão bloqueados.")
            return

        # --- NOVO: FILTRO DE PÂNICO VIX ---
        VIX_PANIC_THRESHOLD = 0.10 # Aumento de 10% no VIX em 1h
        if latest_data.get('vix_close_change', 0) > VIX_PANIC_THRESHOLD:
            logger.warning(f"🚨 FILTRO DE PÂNICO VIX ATIVADO (VIX subiu {latest_data['vix_close_change']:.2%})! Compra bloqueada.")
            return

        # --- NOVO: FILTRO DE VOLUME ---
        if latest_data['volume'] < latest_data['volume_sma_50']:
            logger.info(f"Sinal ignorado. Volume ({latest_data['volume']:.2f}) abaixo da média ({latest_data['volume_sma_50']:.2f}).")
            return

        scaler = self.scalers.get(regime)
        model = self.models.get(regime)
        params = self.strategy_params.get(regime)
        confidence_manager = self.confidence_managers.get(regime)

        features_for_prediction = pd.DataFrame(latest_data[self.model_feature_names]).T
        scaled_features = scaler.transform(features_for_prediction)
        buy_confidence = model.predict_proba(scaled_features)[0][1]
        
        current_confidence_threshold = confidence_manager.get_confidence()
        if buy_confidence > current_confidence_threshold:
            # --- LÓGICA DE RISCO AGRESSIVO E ROBUSTO ---
            base_risk = params.get('risk_per_trade_pct', 0.05)
            if regime == 'RECUPERACAO': base_risk /= 2
            
            signal_strength = (buy_confidence - current_confidence_threshold) / (1.0 - current_confidence_threshold)
            aggression_exponent = params.get('aggression_exponent', 2.0)
            max_risk_scale = params.get('max_risk_scale', 3.0)
            aggression_factor = 0.5 + (signal_strength ** aggression_exponent) * (max_risk_scale - 0.5)
            dynamic_risk_pct = base_risk * aggression_factor
            
            trade_size_usdt = self.portfolio.trading_capital_usdt * dynamic_risk_pct

            # AJUSTE PELA VOLATILIDADE
            current_atr = latest_data.get('atr', 0)
            long_term_atr = latest_data.get('atr_long_avg', current_atr)
            if long_term_atr > 0 and current_atr > 0:
                volatility_factor = current_atr / long_term_atr
                risk_dampener = np.clip(1 / volatility_factor, 0.6, 1.2)
                trade_size_usdt *= risk_dampener

            # --- NOVO: TETO MÁXIMO DE ALOCAÇÃO POR TRADE ---
            MAX_CAPITAL_PER_TRADE_PCT = 0.25
            max_allowed_size = self.portfolio.trading_capital_usdt * MAX_CAPITAL_PER_TRADE_PCT
            if trade_size_usdt > max_allowed_size:
                logger.warning(f"Tamanho do trade ({trade_size_usdt:,.2f}) excedeu o teto. Reduzido para {max_allowed_size:,.2f}.")
                trade_size_usdt = max_allowed_size

            if trade_size_usdt < 10: # Mínimo da Binance
                logger.warning(f"Sinal ignorado. Valor final do trade ({trade_size_usdt:.2f}) abaixo do mínimo.")
                return

            # --- MUDANÇA: STOP LOSS COM ATR ---
            current_price = latest_data['close']
            stop_loss_atr_multiplier = params.get('stop_loss_atr_multiplier', 2.5)
            stop_price = current_price - (latest_data['atr'] * stop_loss_atr_multiplier)

            self._execute_buy(current_price, trade_size_usdt, stop_price, buy_confidence, regime, params)

    # --- MUDANÇA --- Assinatura da função de compra alterada para receber o stop price
    def _execute_buy(self, price, trade_size_usdt, stop_price, confidence, regime, params: dict):
        try:
            buy_price_expected = price * (1 + SLIPPAGE_RATE)
            quantity_to_buy = trade_size_usdt / buy_price_expected
            logger.info(f"EXECUTANDO ORDEM DE COMPRA: {quantity_to_buy:.8f} BTC a ~${price:,.2f}")

            # ... (lógica de criar ordem na Binance) ...
            
            self.buy_price = buy_price_expected
            self.in_trade_position = True
            self.position_phase = 'INITIAL'
            self.current_stop_price = stop_price # Usa o stop calculado
            self.highest_price_in_trade = self.buy_price
            self.last_used_params = {**params, 'entry_regime': regime}
            
            self.portfolio.update_on_buy(quantity_to_buy, trade_size_usdt, self.buy_price)
            self._log_trade("BUY", self.buy_price, quantity_to_buy, f"Sinal do ML ({confidence:.2%})", 0, 0)
        except Exception as e:
            logger.error(f"ERRO AO EXECUTAR COMPRA: {e}", exc_info=True)
            self.in_trade_position = False

    def _execute_sell(self, price, reason, partial=False, amount_to_sell=None):
        # A lógica de venda permanece a mesma.
        # ... (código do _execute_sell como no arquivo original) ...
        if amount_to_sell is None: amount_to_sell = self.portfolio.trading_btc_balance
        if amount_to_sell <= 0: return

        try:
            logger.info(f"EXECUTANDO ORDEM DE VENDA: {amount_to_sell:.8f} BTC a ~${price:,.2f} | Motivo: {reason}")
            sell_price_expected = price * (1 - SLIPPAGE_RATE)
            # ... (lógica de criar ordem de venda) ...
            revenue = sell_price_expected * amount_to_sell
            pnl_usdt = (sell_price_expected - self.buy_price) * amount_to_sell
            pnl_pct = (sell_price_expected / self.buy_price) - 1 if self.buy_price > 0 else 0
            
            entry_regime = self.last_used_params.get('entry_regime', 'LATERAL')
            confidence_manager = self.confidence_managers.get(entry_regime, list(self.confidence_managers.values())[0])

            self.portfolio.update_on_sell(amount_to_sell, revenue, pnl_usdt, sell_price_expected, self.last_used_params)
            confidence_manager.update(pnl_pct)
            self._log_trade("SELL", sell_price_expected, amount_to_sell, reason, pnl_usdt, pnl_pct)
            
            if not partial:
                self.in_trade_position = False; self.position_phase = None; self.last_used_params = {}
        except Exception as e:
            logger.error(f"ERRO AO EXECUTAR VENDA: {e}", exc_info=True)

    def _initialize_trade_log(self):
        # ... (código do _initialize_trade_log como no arquivo original) ...
        if not os.path.exists(TRADES_LOG_FILE):
            with open(TRADES_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'type', 'price', 'quantity', 'pnl_usdt', 'pnl_percent', 'reason'])

    def _log_trade(self, trade_type, price, qty, reason, pnl_usdt=0, pnl_pct=0):
        # ... (código do _log_trade como no arquivo original) ...
        with open(TRADES_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([pd.Timestamp.now(tz='UTC').isoformat(), trade_type, price, qty, pnl_usdt, pnl_pct, reason])

    # --- MUDANÇA --- Salvando e carregando o estado do circuit breaker
    def _save_state(self):
        state = {
            'in_trade_position': self.in_trade_position,
            'buy_price': self.buy_price,
            'position_phase': self.position_phase,
            'current_stop_price': self.current_stop_price,
            'highest_price_in_trade': self.highest_price_in_trade,
            'last_used_params': self.last_used_params,
            'portfolio': self.portfolio.__dict__,
            'session_peak_value': self.session_peak_value,
            'session_drawdown_stop_activated': self.session_drawdown_stop_activated
        }
        with open(BOT_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)

    def _load_state(self):
        if not os.path.exists(BOT_STATE_FILE): return False
        try:
            with open(BOT_STATE_FILE, 'r') as f:
                state = json.load(f)
            
            self.in_trade_position = state.get('in_trade_position', False)
            # ... (carregando o resto do estado) ...
            portfolio_state = state.get('portfolio', {})
            # ...
            
            self.session_peak_value = state.get('session_peak_value', 0.0)
            self.session_drawdown_stop_activated = state.get('session_drawdown_stop_activated', False)

            logger.info("✅ Estado anterior do bot e portfólio carregado com sucesso.")
            # ... (lógica de restaurar e logar status) ...
            return True
        except Exception as e:
            logger.error(f"Não foi possível carregar o estado anterior: {e}. Iniciando com um estado limpo.")
            if os.path.exists(BOT_STATE_FILE): os.remove(BOT_STATE_FILE)
            return False

    def graceful_shutdown(self, signum, frame):
        # ... (código do graceful_shutdown como no arquivo original) ...
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO DE FORMA SEGURA... 🚨")
        self._save_state()
        logger.info("Estado do bot salvo. Desligando.")
        sys.exit(0)