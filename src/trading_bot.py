# src/trading_bot.py (VERSÃO 2.0 - ESTRATÉGIA MULTI-CAMADA)

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
from binance.exceptions import BinanceAPIException
from tabulate import tabulate

from src.logger import logger
from src.config import (
    API_KEY, API_SECRET, USE_TESTNET, SYMBOL, MODEL_FILE, SCALER_FILE, TRADES_LOG_FILE,
    BOT_STATE_FILE, STRATEGY_PARAMS_FILE, MAX_USDT_ALLOCATION
)
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
# <<< PASSO 1: Importar o cérebro tático >>>
from src.confidence_manager import AdaptiveConfidenceManager

# --- Constantes da Estratégia (podem ser movidas para config.py no futuro) ---
PARTIAL_SELL_PCT = 0.5       # Vende 50% na realização de lucro parcial
TREASURY_ALLOCATION_PCT = 0.20 # 20% do lucro vai para o Tesouro de BTC

class PortfolioManager:
    """
    Gerencia o estado do portfólio, capital e risco.
    AGORA INCLUI A GESTÃO DO TESOURO DE BTC.
    """
    def __init__(self, client):
        self.client = client
        self.max_usdt_allocation = MAX_USDT_ALLOCATION
        
        # Estado Financeiro
        self.trading_capital_usdt = 0.0
        self.trading_btc_balance = 0.0
        self.long_term_btc_holdings = 0.0 # O "Tesouro"
        
        # Métricas de Performance da Sessão
        self.initial_total_value_usdt = 0.0
        self.session_pnl_usdt = 0.0

    def sync_with_live_balance(self):
        """Sincroniza o estado do portfólio com o saldo REAL da conta na Binance."""
        if not self.client:
            logger.error("Cliente Binance indisponível. Não é possível sincronizar o portfólio.")
            return False
        try:
            logger.info("Sincronizando com o saldo real da conta Binance...")
            # (Lógica de sincronização original mantida, mas simplificada para clareza)
            # Em um cenário real, a gestão do que é 'trading' vs 'long_term' na conta da exchange é complexa.
            # Aqui, assumimos que o bot gerencia uma alocação específica.
            account_info = self.client.get_account()
            usdt_balance = next((item for item in account_info['balances'] if item['asset'] == 'USDT'), {'free': '0'})
            btc_balance = next((item for item in account_info['balances'] if item['asset'] == SYMBOL.replace("USDT", "")), {'free': '0'})
            usdt_balance = float(usdt_balance['free'])
            # O saldo BTC aqui é considerado o nosso Tesouro inicial. O bot de trade começa com 0.
            self.long_term_btc_holdings = float(btc_balance['free'])
            
            # Define o capital de trabalho para o trading
            self.trading_capital_usdt = min(usdt_balance, self.max_usdt_allocation)
            self.trading_btc_balance = 0.0 # O bot começa sem posição de trade
            
            current_price = float(self.client.get_symbol_ticker(symbol=SYMBOL)['price'])
            self.initial_total_value_usdt = self.get_total_portfolio_value_usdt(current_price)
            
            logger.info("--- Portfólio Sincronizado com Saldo Real ---")
            self.log_portfolio_status(current_price, "STATUS INICIAL")
            return True
            
        except Exception as e:
            logger.error(f"Falha ao sincronizar com o saldo da Binance: {e}", exc_info=True)
            return False

    def update_on_buy(self, bought_btc_amount, cost_usdt, price):
        self.trading_capital_usdt -= cost_usdt
        self.trading_btc_balance += bought_btc_amount
        self.log_portfolio_status(price, "COMPRA EXECUTADA")

    def update_on_sell(self, sold_btc_amount, revenue_usdt, profit_usdt, price):
        """Atualiza o portfólio após uma venda, incluindo a alocação para o tesouro."""
        self.trading_btc_balance -= sold_btc_amount
        
        if profit_usdt > 0:
            # Alocação para o Tesouro de BTC
            treasury_usdt = profit_usdt * TREASURY_ALLOCATION_PCT
            reinvestment_usdt = revenue_usdt - treasury_usdt
            
            # Apenas o reinvestimento volta para o capital de trading
            self.trading_capital_usdt += reinvestment_usdt
            
            # O valor do tesouro é convertido para BTC e adicionado ao holding
            treasury_btc = treasury_usdt / price
            self.long_term_btc_holdings += treasury_btc
            logger.info(f"💰 Lucro de ${profit_usdt:.2f} realizado. Alocado ${treasury_usdt:.2f} ({treasury_btc:.8f} BTC) para o Tesouro.")
        else:
            # Se foi uma perda ou breakeven, todo o valor volta para o capital
            self.trading_capital_usdt += revenue_usdt
            
        self.log_portfolio_status(price, "VENDA EXECUTADA")
        
    def get_total_portfolio_value_usdt(self, current_btc_price):
        """Calcula o valor total do portfólio (Trading + Tesouro)."""
        trading_value = self.trading_capital_usdt + (self.trading_btc_balance * current_btc_price)
        holding_value = self.long_term_btc_holdings * current_btc_price
        return trading_value + holding_value
        
    def log_portfolio_status(self, current_btc_price, event_title="STATUS ATUAL"):
        """Imprime um painel de status claro e formatado."""
        if current_btc_price is None or current_btc_price <= 0: return

        total_value = self.get_total_portfolio_value_usdt(current_btc_price)
        self.session_pnl_usdt = total_value - self.initial_total_value_usdt
        
        # Prepara os dados para a tabela
        status_data = [
            ["Capital de Trading (USDT)", f"${self.trading_capital_usdt:,.2f}"],
            ["Posição de Trading (BTC)", f"{self.trading_btc_balance:.8f} BTC"],
            ["Valor da Posição (USDT)", f"${(self.trading_btc_balance * current_btc_price):,.2f}"],
            ["Tesouro de Longo Prazo (BTC)", f"{self.long_term_btc_holdings:.8f} BTC"],
            ["Valor do Tesouro (USDT)", f"${(self.long_term_btc_holdings * current_btc_price):,.2f}"],
        ]
        summary_data = [
            ["Valor Total do Portfólio", f"${total_value:,.2f}"],
            ["Lucro/Prejuízo da Sessão", f"${self.session_pnl_usdt:,.2f}"]
        ]
        
        logger.info("\n" + "="*50 + f"\n--- {event_title} ---")
        print(tabulate(status_data, tablefmt="grid"))
        print(tabulate(summary_data, tablefmt="grid"))
        logger.info("="*50)

class TradingBot:
    def __init__(self):
        self.data_manager = DataManager()
        self.client = self.data_manager.client
        self.portfolio = PortfolioManager(self.client)
        self.model = None
        self.scaler = None
        self.strategy_params = {}

        # <<< PASSO 2: Instanciar o cérebro tático e carregar seu estado >>>
        self.confidence_manager = None 

        # Estado da Posição Ativa
        self.in_trade_position = False
        self.buy_price = 0.0
        self.position_phase = None
        self.current_stop_price = 0.0
        self.highest_price_in_trade = 0.0
        
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def graceful_shutdown(self, signum, frame):
        logger.info("\n" + "="*50)
        logger.info("PARADA SOLICITADA. ENCERRANDO O BOT DE FORMA SEGURA...")
        self._save_state()
        logger.info("Estado final do bot salvo.")
        logger.info("="*50)
        sys.exit(0)

    def _initialize_trade_log(self):
        header = ['timestamp', 'type', 'price', 'quantity_btc', 'value_usdt', 'reason', 'pnl_usdt', 'pnl_percent', 'total_portfolio_value_usdt']
        if not os.path.exists(TRADES_LOG_FILE):
            with open(TRADES_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(header)

    def _log_trade(self, trade_type, price, quantity_btc, reason, pnl_usdt=None, pnl_percent=None):
        current_total_value = self.portfolio.get_total_portfolio_value_usdt(price)
        with open(TRADES_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                pd.Timestamp.now(tz='UTC'), trade_type, f"{price:.2f}", f"{quantity_btc:.8f}",
                f"{price * quantity_btc:.2f}", reason,
                f"{pnl_usdt:.2f}" if pnl_usdt is not None else "",
                f"{pnl_percent:.4f}" if pnl_percent is not None else "",
                f"{current_total_value:.2f}"
            ])

    def _save_state(self):
        # Salva o estado do portfólio e da posição de trade
        portfolio_state = {k: v for k, v in self.portfolio.__dict__.items() if k != 'client'}
        
        # Salva também o estado do confidence_manager
        confidence_state = {
            'current_confidence': self.confidence_manager.current_confidence,
            'pnl_history': list(self.confidence_manager.pnl_history)
        }
        
        state = {
            'in_trade_position': self.in_trade_position,
            'buy_price': self.buy_price,
            'position_phase': self.position_phase,
            'current_stop_price': self.current_stop_price,
            'highest_price_in_trade': self.highest_price_in_trade,
            'portfolio': portfolio_state,
            'confidence_manager': confidence_state,
        }
        with open(BOT_STATE_FILE, 'w') as f: json.dump(state, f, indent=4)
        logger.info("Estado do bot salvo.")

    def _load_state(self):
        if not os.path.exists(BOT_STATE_FILE):
            logger.info("Nenhum arquivo de estado encontrado. Iniciando com um portfólio novo.")
            return False
            
        try:
            with open(BOT_STATE_FILE, 'r') as f: state = json.load(f)
            # Carrega estado da posição
            self.in_trade_position = state.get('in_trade_position', False)
            self.buy_price = state.get('buy_price', 0.0)
            self.position_phase = state.get('position_phase')
            self.current_stop_price = state.get('current_stop_price', 0.0)
            self.highest_price_in_trade = state.get('highest_price_in_trade', 0.0)
            
            # Carrega estado do portfólio
            if 'portfolio' in state: self.portfolio.__dict__.update(state['portfolio'])
            
            # Carrega estado do confidence manager
            if 'confidence_manager' in state and self.confidence_manager:
                confidence_state = state['confidence_manager']
                self.confidence_manager.current_confidence = confidence_state.get('current_confidence')
                self.confidence_manager.pnl_history.clear()
                self.confidence_manager.pnl_history.extend(confidence_state.get('pnl_history', []))

            logger.info("Estado anterior do bot carregado com sucesso.")
            return True
        except Exception as e:
            logger.error(f"Erro ao ler o arquivo de estado: {e}. Reiniciando do zero.")
            return False

    def load_model_and_params(self):
        try:
            self.model, self.scaler = joblib.load(MODEL_FILE), joblib.load(SCALER_FILE)
            with open(STRATEGY_PARAMS_FILE, 'r') as f: self.strategy_params = json.load(f)

            # <<< PASSO 3: Inicializar o ConfidenceManager com os parâmetros otimizados >>>
            self.confidence_manager = AdaptiveConfidenceManager(
                initial_confidence=self.strategy_params.get('initial_confidence', 0.6),
                learning_rate=self.strategy_params.get('confidence_learning_rate', 0.05)
            )
            logger.info("✅ Modelo, normalizador, parâmetros e cérebro tático carregados.")
            return True
        except FileNotFoundError as e:
            logger.error(f"ERRO: Arquivo '{e.filename}' não encontrado. Execute 'optimize' primeiro.")
            return False

    def _prepare_prediction_data(self):
        # (Função original mantida, mas agora o DataFrame terá a coluna 'market_regime')
        try:
            df_combined = self.data_manager.update_and_load_data(SYMBOL, '1m')
            if df_combined.empty or len(df_combined) < 200:
                logger.warning(f"Dados insuficientes para predição ({len(df_combined)} linhas).")
                return None, None
            trainer = ModelTrainer() # Temporário, idealmente as features seriam uma dependência
            df_features = trainer._prepare_features(df_combined.copy())
            if df_features.empty:
                logger.warning("DataFrame de features vazio após preparo.")
                return None, None
            
            # Retorna a última linha de features e o preço de fechamento correspondente
            return df_features.iloc[[-1]]
            
        except Exception as e:
            logger.error(f"Erro ao preparar dados para predição: {e}", exc_info=True)
            return None

    def execute_trade(self, side, quantity):
        """Envia uma ordem de mercado para a exchange. Retorna múltiplos valores."""
        try:
            # A Binance para BTCUSDT exige precisão de 5 casas decimais na quantidade
            formatted_quantity = f"{quantity:.5f}"
            logger.info(f"Enviando ordem de mercado: Lado={side}, Quantidade={formatted_quantity}")
            
            if self.client.testnet:
                # Simulação para testnet para não gastar dinheiro real
                logger.warning("MODO TESTNET: Simulando execução de ordem.")
                current_price = self.portfolio.get_total_portfolio_value_usdt(1) / (self.portfolio.trading_capital_usdt + self.portfolio.trading_btc_balance) # Estima preço
                cost_or_revenue = current_price * quantity
                return {"symbol": SYMBOL, "status": "FILLED"}, current_price, quantity, cost_or_revenue

            order = self.client.create_order(symbol=SYMBOL, side=side, type=Client.ORDER_TYPE_MARKET, quantity=formatted_quantity)
            logger.info(f"ORDEM EXECUTADA: {order}")
            
            # Processa os preenchimentos da ordem para obter preço médio e valor total
            fills = order.get('fills', [])
            if not fills: return order, 0.0, 0.0, 0.0

            avg_price = sum(float(f['price']) * float(f['qty']) for f in fills) / sum(float(f['qty']) for f in fills)
            executed_qty = sum(float(f['qty']) for f in fills)
            total_value = sum(float(f['price']) * float(f['qty']) for f in fills)

            return order, avg_price, executed_qty, total_value
        except BinanceAPIException as e:
            logger.error(f"ERRO DE API AO EXECUTAR ORDEM: {e}")
        except Exception as e:
            logger.error(f"ERRO INESPERADO AO EXECUTAR ORDEM: {e}", exc_info=True)
        return None, 0.0, 0.0, 0.0

    def run(self):
        """O loop principal do bot de trading, agora com a estratégia multi-camada."""
        if not self.client:
            logger.error("Cliente Binance não inicializado. O bot não pode operar.")
            return

        if not self.load_model_and_params(): return
        self._initialize_trade_log()
        
        if not self._load_state():
            if not self.portfolio.sync_with_live_balance():
                logger.error("Falha fatal ao inicializar portfólio. Abortando.")
                return
        
        logger.info(">>> INICIANDO LOOP DE TRADING <<<")
        while True:
            try:
                latest_features_df = self._prepare_prediction_data()
                if latest_features_df is None:
                    time.sleep(60)
                    continue

                current_price = latest_features_df['close'].iloc[0]
                
                # --- LÓGICA DE GESTÃO DA POSIÇÃO ATIVA ---
                if self.in_trade_position:
                    self._manage_active_position(current_price)
                
                # --- LÓGICA DE ENTRADA ---
                else:
                    self._check_for_entry_signal(latest_features_df)

                # Log de status a cada ciclo para monitoramento
                if not self.in_trade_position:
                    self.portfolio.log_portfolio_status(current_price)

                time.sleep(60)
            
            except KeyboardInterrupt:
                self.graceful_shutdown(None, None)
            except Exception as e:
                logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
                time.sleep(60)
                
    def _manage_active_position(self, price: float):
        """Lógica da Camada 3: Gerencia uma posição aberta."""
        self.highest_price_in_trade = max(self.highest_price_in_trade, price)
        
        # 1. VERIFICA O STOP LOSS PRIMEIRO
        if price <= self.current_stop_price:
            logger.info(f"🔴 STOP LOSS ATINGIDO a ${price:,.2f} (Stop era ${self.current_stop_price:,.2f})")
            pnl_pct = (price / self.buy_price) - 1
            self._execute_sell(price, f"Stop Loss ({pnl_pct:.2%})")
            return

        # 2. LÓGICA DE FASES
        if self.position_phase == 'INITIAL':
            if price >= self.buy_price * (1 + self.strategy_params['stop_loss_threshold']):
                self.position_phase = 'BREAKEVEN'
                self.current_stop_price = self.buy_price * (1 + (0.001 * 2)) # Custo de taxas
                logger.info(f"✅ POSIÇÃO SEGURA! Stop movido para Breakeven em ${self.current_stop_price:,.2f}")
                self._save_state()

        elif self.position_phase == 'BREAKEVEN':
            if price >= self.buy_price * (1 + self.strategy_params['profit_threshold']):
                logger.info(f"💰 REALIZAÇÃO PARCIAL! Preço atingiu alvo de {self.strategy_params['profit_threshold']:.2%}")
                amount_to_sell = self.portfolio.trading_btc_balance * PARTIAL_SELL_PCT
                self._execute_sell(price, "Realização Parcial de Lucro", partial=True, amount_to_sell=amount_to_sell)
                self.position_phase = 'TRAILING' # Move para a fase final
                self._save_state()

        elif self.position_phase == 'TRAILING':
            trailing_stop_pct = self.strategy_params['stop_loss_threshold'] * 1.5
            new_trailing_stop = self.highest_price_in_trade * (1 - trailing_stop_pct)
            if new_trailing_stop > self.current_stop_price:
                self.current_stop_price = new_trailing_stop
                logger.info(f"📈 TRAILING STOP ATUALIZADO para ${self.current_stop_price:,.2f}")
                self._save_state()

    def _check_for_entry_signal(self, features_df: pd.DataFrame):
        """Lógica das Camadas 1 e 2: Verifica se deve entrar em uma nova posição."""
        
        # --- CAMADA 1: O GENERAL ---
        regime = features_df['market_regime'].iloc[0]
        base_risk = self.strategy_params.get('risk_per_trade_pct', 0.05)
        
        if regime == 'BEAR':
            logger.debug(f"Regime 'BEAR' detectado. Trades de compra bloqueados.")
            return
        elif regime == 'RECUPERACAO':
            base_risk /= 2
        elif regime == 'LATERAL':
            base_risk /= 4

        # --- CAMADA 2: O CAPITÃO ---
        scaled_features = self.scaler.transform(features_df[self.trainer.feature_names]) # Usar self.trainer.feature_names
        buy_confidence = self.model.predict_proba(scaled_features)[0][1]
        
        # <<< PASSO 4: Usar o cérebro tático para a decisão de entrada >>>
        current_confidence_threshold = self.confidence_manager.get_confidence()
        
        logger.info(
            f"Preço: ${features_df['close'].iloc[0]:,.2f} | "
            f"Regime: {regime} | "
            f"Conf. Modelo: {buy_confidence:.2%} > Limiar: {current_confidence_threshold:.2%}"
        )

        if buy_confidence > current_confidence_threshold:
            signal_strength = (buy_confidence - current_confidence_threshold) / (1.0 - current_confidence_threshold)
            dynamic_risk_pct = base_risk * (0.5 + signal_strength)
            trade_size_usdt = self.portfolio.trading_capital_usdt * dynamic_risk_pct
            
            logger.info(f"🎯 SINAL DE COMPRA CONFIRMADO! Risco dinâmico: {dynamic_risk_pct:.2%}. Planejando trade de ~${trade_size_usdt:,.2f}.")

            if self.portfolio.trading_capital_usdt >= trade_size_usdt and trade_size_usdt > 10:
                self._execute_buy(features_df['close'].iloc[0], trade_size_usdt, buy_confidence)
            else:
                logger.warning("Sinal de compra ignorado. Capital de trading ou tamanho do trade insuficientes.")
                
    def _execute_buy(self, price, trade_size_usdt, confidence):
        """Executa a lógica de compra."""
        quantity_to_buy = trade_size_usdt / price
        order, buy_price_filled, bought_qty, cost = self.execute_trade(Client.SIDE_BUY, quantity_to_buy)
        
        if order and bought_qty > 0:
            self.buy_price = buy_price_filled
            self.in_trade_position = True
            self.position_phase = 'INITIAL'
            self.current_stop_price = self.buy_price * (1 - self.strategy_params['stop_loss_threshold'])
            self.highest_price_in_trade = self.buy_price
            
            self.portfolio.update_on_buy(bought_qty, cost, buy_price_filled)
            self._log_trade("BUY", buy_price_filled, bought_qty, f"Sinal do ML ({confidence:.2%})")
            self._save_state()

    def _execute_sell(self, price, reason, partial=False, amount_to_sell=None):
        """Executa a lógica de venda, total ou parcial."""
        if amount_to_sell is None:
            amount_to_sell = self.portfolio.trading_btc_balance
        
        if amount_to_sell <= 0: return

        order, sell_price, sold_qty, revenue = self.execute_trade(Client.SIDE_SELL, amount_to_sell)
        
        if order and sold_qty > 0:
            pnl_usdt = (sell_price - self.buy_price) * sold_qty
            pnl_pct = (sell_price / self.buy_price) - 1 if self.buy_price > 0 else 0
            
            self.portfolio.update_on_sell(sold_qty, revenue, pnl_usdt, sell_price)
            self.confidence_manager.update(pnl_pct) # O cérebro sempre aprende com o resultado
            
            self._log_trade("SELL", sell_price, sold_qty, reason, pnl_usdt, pnl_pct)
            
            if not partial:
                self.in_trade_position = False
                self.position_phase = None
            
            self._save_state()