# src/trading_bot.py

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

from src.logger import logger
from src.config import (
    API_KEY, API_SECRET, USE_TESTNET, SYMBOL, MODEL_FILE, SCALER_FILE, TRADES_LOG_FILE,
    BOT_STATE_FILE, STRATEGY_PARAMS_FILE, MAX_USDT_ALLOCATION,
    LONG_TERM_HOLD_PCT, RISK_PER_TRADE_PCT
)
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer

class PortfolioManager:
    """
    Classe dedicada para gerenciar o estado do portfólio, capital e risco,
    sincronizando com o saldo real da conta para uma gestão 100% dinâmica.
    """
    def __init__(self, client):
        self.client = client
        self.max_usdt_allocation = MAX_USDT_ALLOCATION
        self.long_term_hold_pct = LONG_TERM_HOLD_PCT
        self.risk_per_trade_pct = RISK_PER_TRADE_PCT
        
        # Estado do portfólio
        self.long_term_btc_holdings = 0.0
        self.trading_capital_usdt = 0.0
        self.trading_btc_balance = 0.0

    def sync_with_live_balance(self):
        """
        Sincroniza o estado do portfólio com o saldo REAL da conta na Binance.
        Esta é a função mais importante para a gestão dinâmica.
        """
        try:
            logger.info("Sincronizando com o saldo real da conta Binance...")
            current_price = float(self.client.get_symbol_ticker(symbol=SYMBOL)['price'])
            
            usdt_balance = float(self.client.get_asset_balance(asset='USDT')['free'])
            btc_balance = float(self.client.get_asset_balance(asset=SYMBOL.replace("USDT", ""))['free'])
            
            real_total_portfolio_usdt = usdt_balance + (btc_balance * current_price)
            logger.info(f"Saldo real detectado: {usdt_balance:,.2f} USDT e {btc_balance:.8f} BTC. Valor total: ${real_total_portfolio_usdt:,.2f}")
            
            working_capital = min(real_total_portfolio_usdt, self.max_usdt_allocation)
            logger.info(f"Capital de trabalho para o bot definido em: ${working_capital:,.2f} (menor valor entre o saldo real e a alocação máxima)")

            # Recalcula as alocações com base no capital de trabalho atual
            self.long_term_btc_holdings = (working_capital * self.long_term_hold_pct) / current_price
            self.trading_capital_usdt = working_capital * (1 - self.long_term_hold_pct)
            self.trading_btc_balance = 0.0 # Zera o BTC de trading, pois ele será gerenciado pelas operações

            logger.info("--- Portfólio Sincronizado com Saldo Real ---")
            self.log_portfolio_status(current_price)
            return True
        except Exception as e:
            logger.error(f"Falha ao sincronizar com o saldo da Binance: {e}")
            return False

    def get_trade_size_usdt(self):
        """Calcula o valor em USDT a ser usado em um novo trade, baseado no risco."""
        return self.trading_capital_usdt * self.risk_per_trade_pct

    def update_on_buy(self, bought_btc_amount, buy_price_usdt):
        cost_usdt = bought_btc_amount * buy_price_usdt
        self.trading_capital_usdt -= cost_usdt
        self.trading_btc_balance += bought_btc_amount
        logger.info("PORTFÓLIO ATUALIZADO (COMPRA):")
        self.log_portfolio_status(buy_price_usdt)

    def update_on_sell(self, sold_btc_amount, sell_price_usdt):
        revenue_usdt = sold_btc_amount * sell_price_usdt
        self.trading_capital_usdt += revenue_usdt
        self.trading_btc_balance -= sold_btc_amount
        logger.info("PORTFÓLIO ATUALIZADO (VENDA):")
        self.log_portfolio_status(sell_price_usdt)
        
    def get_total_portfolio_value_usdt(self, current_btc_price):
        trading_value = self.trading_capital_usdt + (self.trading_btc_balance * current_btc_price)
        holding_value = self.long_term_btc_holdings * current_btc_price
        return trading_value + holding_value
        
    def log_portfolio_status(self, current_btc_price):
        if current_btc_price is None or current_btc_price <= 0: return
        total_value = self.get_total_portfolio_value_usdt(current_btc_price)
        logger.info(f"  - Valor Total do Portfólio: ${total_value:,.2f}")
        logger.info(f"  - Capital de Trading (USDT): ${self.trading_capital_usdt:,.2f}")
        logger.info(f"  - Capital de Trading (BTC): {self.trading_btc_balance:.8f}")
        logger.info(f"  - Holding de Longo Prazo (BTC): {self.long_term_btc_holdings:.8f}")

class TradingBot:
    def __init__(self):
        self.client = Client(API_KEY, API_SECRET, tld='com', testnet=USE_TESTNET)
        self.model = None
        self.scaler = None
        self.data_manager = DataManager()
        self.portfolio = PortfolioManager(self.client)
        
        self.in_trade_position = False
        self.buy_price = 0.0
        
        self.strategy_params = {}
        
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def graceful_shutdown(self, signum, frame):
        logger.info("="*50)
        logger.info("PARADA SOLICITADA. ENCERRANDO O BOT DE FORMA SEGURA...")
        self._save_state()
        logger.info("Estado final do bot salvo.")
        logger.info("="*50)
        sys.exit(0)

    def _initialize_trade_log(self):
        header = [
            'timestamp', 'type', 'price', 'quantity_btc', 'value_usdt', 'reason', 
            'pnl_usdt', 'pnl_percent', 'total_portfolio_value_usdt', 
            'trading_capital_usdt', 'trading_btc_balance', 'long_term_btc_holdings'
        ]
        if not os.path.exists(TRADES_LOG_FILE):
            with open(TRADES_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(header)

    def _log_trade(self, trade_type, price, quantity_btc, reason, current_btc_price, pnl_usdt=None, pnl_percent=None):
        with open(TRADES_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                pd.Timestamp.now(tz='UTC'), trade_type, f"{price:.2f}", f"{quantity_btc:.8f}", 
                f"{price * quantity_btc:.2f}", reason,
                f"{pnl_usdt:.2f}" if pnl_usdt is not None else "",
                f"{pnl_percent:.4f}" if pnl_percent is not None else "",
                f"{self.portfolio.get_total_portfolio_value_usdt(current_btc_price):.2f}",
                f"{self.portfolio.trading_capital_usdt:.2f}",
                f"{self.portfolio.trading_btc_balance:.8f}",
                f"{self.portfolio.long_term_btc_holdings:.8f}"
            ])

    def _save_state(self):
        # O objeto `client` não pode ser salvo em JSON, então o removemos antes de salvar.
        portfolio_state = self.portfolio.__dict__.copy()
        portfolio_state.pop('client', None)

        state = {
            'in_trade_position': self.in_trade_position,
            'buy_price': self.buy_price,
            'portfolio': portfolio_state
        }
        with open(BOT_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        logger.info(f"Estado do bot salvo.")

    def _load_state(self):
        if os.path.exists(BOT_STATE_FILE):
            try:
                with open(BOT_STATE_FILE, 'r') as f:
                    state = json.load(f)
                self.in_trade_position = state.get('in_trade_position', False)
                self.buy_price = state.get('buy_price', 0.0)
                if 'portfolio' in state:
                    self.portfolio.__dict__.update(state['portfolio'])
                logger.info("Estado do bot carregado com sucesso.")
                return True
            except Exception as e:
                logger.error(f"Erro ao ler o arquivo de estado: {e}. Iniciando do zero.")
        else:
            logger.info("Nenhum arquivo de estado encontrado. Iniciando do zero.")
        return False

    def load_model(self):
        try:
            self.model = joblib.load(MODEL_FILE)
            self.scaler = joblib.load(SCALER_FILE)
            logger.info("✅ Modelo e normalizador carregados com sucesso.")
            return True
        except FileNotFoundError:
            logger.error("ERRO: Arquivos de modelo/normalizador não encontrados. Execute o modo 'optimize' primeiro.")
            return False

    def _load_strategy_params(self):
        try:
            with open(STRATEGY_PARAMS_FILE, 'r') as f:
                self.strategy_params = json.load(f)
            logger.info(f"✅ Parâmetros da estratégia carregados: {self.strategy_params}")
        except FileNotFoundError:
            logger.warning(f"Arquivo de parâmetros '{STRATEGY_PARAMS_FILE}' não encontrado. Use o modo 'optimize' para gerá-lo.")

    def _prepare_prediction_data(self):
        try:
            end_date = pd.Timestamp.now(tz='UTC')
            start_date = end_date - pd.Timedelta(days=2)
            df_combined = self.data_manager.get_historical_data_by_batch(SYMBOL, '1m', start_date, end_date)
            if df_combined.empty: return pd.DataFrame(), None
            trainer = ModelTrainer()
            df_features = trainer._prepare_features(df_combined.copy())
            if df_features.empty: return pd.DataFrame(), None
            last_feature_row = df_features.reindex(columns=trainer.feature_names, fill_value=0).tail(1)
            current_price = df_combined['close'].iloc[-1]
            return last_feature_row, current_price
        except Exception as e:
            logger.error(f"Erro ao preparar dados para predição: {e}", exc_info=True)
            return pd.DataFrame(), None

    def execute_trade(self, side, quantity):
        try:
            # A precisão para BTC é geralmente de 6 a 8 casas decimais. 6 é seguro.
            formatted_quantity = "{:.6f}".format(quantity)
            logger.info(f"Enviando ordem: Lado={side}, Quantidade={formatted_quantity}")
            order = self.client.create_order(symbol=SYMBOL, side=side, type=Client.ORDER_TYPE_MARKET, quantity=formatted_quantity)
            logger.info(f"ORDEM ENVIADA: {order}")
            fills = order.get('fills', [])
            if fills:
                avg_price = sum(float(f['price']) * float(f['qty']) for f in fills) / sum(float(f['qty']) for f in fills)
                executed_qty = sum(float(f['qty']) for f in fills)
                return order, avg_price, executed_qty
            return order, float(order.get('price', 0)), float(order.get('executedQty', 0))
        except BinanceAPIException as e:
            logger.error(f"ERRO DE API AO EXECUTAR ORDEM: {e}")
            return None, None, None
        except Exception as e:
            logger.error(f"ERRO INESPERADO AO EXECUTAR ORDEM: {e}")
            return None, None, None

    def run(self):
        if not self.load_model(): return
        
        self._initialize_trade_log()
        self._load_strategy_params()
        
        if not self._load_state():
            if not self.portfolio.sync_with_live_balance():
                logger.error("Não foi possível inicializar o portfólio com o saldo real. Abortando.")
                return

        self.portfolio.log_portfolio_status(self.data_manager.get_current_price(SYMBOL))

        while True:
            try:
                features_df, current_price = self._prepare_prediction_data()
                if features_df.empty or current_price is None:
                    time.sleep(60); continue

                if self.in_trade_position:
                    profit_pct = (current_price / self.buy_price) - 1
                    if profit_pct >= self.strategy_params['profit_threshold'] or profit_pct <= -self.strategy_params['stop_loss_threshold']:
                        quantity_to_sell = self.portfolio.trading_btc_balance
                        order, sell_price, executed_qty = self.execute_trade(Client.SIDE_SELL, quantity_to_sell)
                        if order and executed_qty > 0:
                            pnl_usdt = (sell_price - self.buy_price) * executed_qty
                            pnl_percent = (sell_price / self.buy_price) - 1 if self.buy_price > 0 else 0
                            self.portfolio.update_on_sell(executed_qty, sell_price)
                            self._log_trade("SELL", sell_price, executed_qty, "Take-Profit/Stop-Loss", current_price, pnl_usdt, pnl_percent)
                            self.in_trade_position = False
                            self._save_state()
                else:
                    scaled_features = self.scaler.transform(features_df)
                    buy_confidence = self.model.predict_proba(scaled_features)[0][1]
                    logger.info(f"Preço: ${current_price:,.2f} | Confiança de Compra: {buy_confidence:.2%}")
                    
                    if buy_confidence > self.strategy_params.get('prediction_confidence', 0.75):
                        trade_size_usdt = self.portfolio.get_trade_size_usdt()
                        if self.portfolio.trading_capital_usdt >= trade_size_usdt and trade_size_usdt > 10: # Mínimo de $10 para um trade
                            quantity_to_buy = trade_size_usdt / current_price
                            order, buy_price_filled, executed_qty = self.execute_trade(Client.SIDE_BUY, quantity_to_buy)
                            if order and executed_qty > 0:
                                self.buy_price = buy_price_filled
                                self.in_trade_position = True
                                self.portfolio.update_on_buy(executed_qty, buy_price_filled)
                                self._log_trade("BUY", buy_price_filled, executed_qty, f"Sinal do ML ({buy_confidence:.2%})", current_price)
                                self._save_state()
                        else:
                            logger.warning(f"Sinal de compra, mas capital de trading ({self.portfolio.trading_capital_usdt:.2f}) insuficiente ou trade size ({trade_size_usdt:.2f}) muito baixo.")

                logger.info("--- Ciclo concluído, aguardando 60 segundos ---")
                self.portfolio.log_portfolio_status(current_price)
                time.sleep(60)
            except Exception as e:
                logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
                time.sleep(60)