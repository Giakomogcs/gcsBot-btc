# src/quick_tester.py (VERSÃO 6.2 - Simulador Híbrido Fiel)

import json
import pandas as pd
import numpy as np
import joblib
import os
from datetime import datetime, timezone, timedelta

from src.logger import logger, log_table
from src.config import (
    MODEL_METADATA_FILE, SYMBOL, FEE_RATE, SLIPPAGE_RATE, DATA_DIR,
    DCA_IN_BEAR_MARKET_ENABLED, DCA_DAILY_AMOUNT_USDT, DCA_MIN_CAPITAL_USDT
)
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
from src.confidence_manager import AdaptiveConfidenceManager

def calculate_sortino_ratio(series, periods_per_year=365*24*60):
    if len(series) < 2: return 0.0
    returns = series.pct_change().dropna()
    if len(returns) < 2: return 0.0
        
    target_return = 0
    downside_returns = returns[returns < target_return]
    
    expected_return = returns.mean()
    downside_std = downside_returns.std()
    
    if downside_std == 0 or pd.isna(downside_std) or downside_std < 1e-9:
        return 100.0 if expected_return > 0 else 0.0
        
    sortino = (expected_return * periods_per_year) / (downside_std * np.sqrt(periods_per_year))
    return sortino if not pd.isna(sortino) else 0.0

class QuickTester:
    def __init__(self):
        self.data_manager = DataManager()
        self.trainer = ModelTrainer() 
        
        self.models = {}
        self.scalers = {}
        self.strategy_params = {}
        self.confidence_managers = {}
        self.model_feature_names = []

    def load_all_specialists(self):
        try:
            with open(MODEL_METADATA_FILE, 'r') as f:
                metadata = json.load(f)

            valid_until_str = metadata.get('valid_until')
            if not valid_until_str:
                logger.error("ERRO CRÍTICO: Data de validade não encontrada. Execute a otimização.")
                return False

            valid_until_dt = datetime.fromisoformat(valid_until_str)
            if datetime.now(timezone.utc) > valid_until_dt:
                logger.warning("="*60 + "\n🚨 ALERTA: O CONJUNTO DE MODELOS ESTÁ EXPIRADO! 🚨\n" + "="*60)
            else:
                logger.info(f"✅ Modelos válidos até {valid_until_dt.strftime('%Y-%m-%d')}. Verificação OK.")
            
            self.model_feature_names = metadata.get('feature_names', [])
            summary = metadata.get('optimization_summary', {})
            
            if not self.model_feature_names:
                raise ValueError("Lista de features não encontrada nos metadados.")
            
            logger.info(f"Carregando {len(self.model_feature_names)} features esperadas...")

            loaded_specialists_count = 0
            for regime, result in summary.items():
                if result.get('status') == 'Optimized and Saved':
                    try:
                        model_path = os.path.join(DATA_DIR, result['model_file'])
                        scaler_path = model_path.replace('trading_model', 'scaler')
                        params_path = os.path.join(DATA_DIR, result['params_file'])

                        self.models[regime] = joblib.load(model_path)
                        self.scalers[regime] = joblib.load(scaler_path)
                        with open(params_path, 'r') as p:
                            regime_params = json.load(p)
                            self.strategy_params[regime] = regime_params
                        
                        self.confidence_managers[regime] = AdaptiveConfidenceManager(
                            initial_confidence=regime_params.get('initial_confidence', 0.7),
                            learning_rate=regime_params.get('confidence_learning_rate', 0.05),
                            window_size=regime_params.get('confidence_window_size', 10),
                            pnl_clamp_value=regime_params.get('confidence_pnl_clamp', 0.02)
                        )
                        loaded_specialists_count += 1
                    except Exception as e:
                        logger.error(f"Falha ao carregar artefatos para o regime '{regime}': {e}")

            if loaded_specialists_count == 0:
                logger.error("Nenhum especialista de trading foi carregado. Execute a otimização.")
                return False

            logger.info(f"✅ {loaded_specialists_count} especialista(s) carregado(s).")
            return True

        except FileNotFoundError:
            logger.error(f"ERRO: Arquivo de metadados '{MODEL_METADATA_FILE}' não encontrado. Execute a otimização primeiro.")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado ao carregar especialistas: {e}", exc_info=True)
            return False

    # <<< MUDANÇA 1: RELATÓRIO MELHORADO PARA MOSTRAR A TESOURARIA >>>
    def generate_report(self, portfolio_history: list, test_period_days: int, buy_and_hold_return: float, final_treasury_btc: float):
        if not portfolio_history:
            logger.warning("Histórico de portfólio vazio. Não é possível gerar relatório."); return

        df = pd.DataFrame(portfolio_history).set_index('timestamp')
        
        initial_capital = df['total_value'].iloc[0]
        final_capital = df['total_value'].iloc[-1]
        
        total_return = (final_capital / initial_capital) - 1
        annualized_return = ((1 + total_return) ** (365.0 / test_period_days)) - 1 if test_period_days > 0 else 0
        
        running_max = df['total_value'].cummax()
        drawdown = (df['total_value'] - running_max) / running_max
        max_drawdown = drawdown.min()
        
        sortino_ratio = calculate_sortino_ratio(df['total_value'])
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0.0
        
        trades_df = df[df['trade_executed'] > 0]
        total_trades = len(trades_df[trades_df['trade_type'] == 'TRADE'])
        total_dca = len(trades_df[trades_df['trade_type'] == 'DCA'])

        # Painel de Resumo Financeiro
        finance_summary = [
            ["Período Testado", f"{df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d} ({test_period_days} dias)"],
            ["Capital Inicial", f"${initial_capital:,.2f}"],
            ["Capital Final", f"💎 ${final_capital:,.2f}"],
            ["Resultado Total da Estratégia", f"📈 {total_return:+.2%}"],
            ["Retorno do Buy & Hold no Período", f"📊 {buy_and_hold_return:+.2%}"],
        ]
        
        # Painel de Métricas de Performance
        performance_metrics = [
            ["Retorno Anualizado", f"{annualized_return:+.2%}"],
            ["Máximo Drawdown", f"📉 {max_drawdown:.2%}"],
            ["Sortino Ratio (Retorno/Risco)", f"🍀 {sortino_ratio:.2f}"],
            ["Calmar Ratio (Retorno/Drawdown)", f"{calmar_ratio:.2f}"],
        ]

        # Painel de Atividade do Bot
        activity_summary = [
            ["Total de Trades de Lucro", f"{int(total_trades)}"],
            ["Total de Compras de Acumulação (DCA)", f"{int(total_dca)}"],
            ["Tesouraria Final (BTC Acumulado)", f"🏦 {final_treasury_btc:.8f} BTC"],
        ]

        log_table("🏆 RESUMO GERAL DA PERFORMANCE (OUT-OF-SAMPLE)", finance_summary, headers=["Métrica", "Valor"])
        log_table("Métricas de Performance", performance_metrics, headers=["Métrica", "Valor"])
        log_table("Atividade do Bot", activity_summary, headers=["Métrica", "Valor"])


    def run(self, start_date_str: str, end_date_str: str, initial_capital: float = 100.0):
        if not self.load_all_specialists(): return

        logger.info(f"Carregando e preparando dados para o período de teste: {start_date_str} a {end_date_str}...")
        full_data = self.data_manager.update_and_load_data(SYMBOL, '1m')
        test_data = full_data.loc[start_date_str:end_date_str]
        if test_data.empty: 
            logger.error("Não há dados disponíveis para o período de teste."); return
        
        test_features_df, _ = self.trainer._prepare_features(test_data.copy())
        
        buy_and_hold_return = (test_features_df['close'].iloc[-1] / test_features_df['close'].iloc[0]) - 1
        
        capital_usdt = initial_capital
        trading_btc = 0.0
        
        # <<< MUDANÇA 2: ADICIONAR TESOURARIA E TIMER DE DCA À SIMULAÇÃO >>>
        long_term_btc_holdings = 0.0
        last_dca_time = None

        in_position, buy_price, position_phase, current_stop_price, highest_price_in_trade = False, 0.0, None, 0.0, 0.0
        portfolio_history = []
        last_used_params = {}
        
        logger.info("🚀 Iniciando simulação de trading (backtest) com especialistas de regime...")
        for date, row in test_features_df.iterrows():
            price = row['close']
            trade_executed_this_step = 0
            trade_type_this_step = None # Para o relatório final
            
            regime = row.get('market_regime', 'LATERAL')
            params = self.strategy_params.get(regime)
            model, scaler = self.models.get(regime), self.scalers.get(regime)
            confidence_manager = self.confidence_managers.get(regime)
            
            trade_signal_found = False
            if in_position:
                current_params = last_used_params
                highest_price_in_trade = max(highest_price_in_trade, price)
                
                if price <= current_stop_price:
                    sell_price = price * (1 - SLIPPAGE_RATE)
                    revenue = trading_btc * sell_price
                    pnl_usdt = revenue * (1-FEE_RATE) - (buy_price * trading_btc * (1+FEE_RATE))
                    pnl_pct = (sell_price / buy_price) - 1 if buy_price > 0 else 0
                    
                    if pnl_usdt > 0:
                        treasury_usdt = pnl_usdt * current_params.get('treasury_allocation_pct', 0.20)
                        revenue -= treasury_usdt
                        long_term_btc_holdings += treasury_usdt / price if price > 0 else 0
                        
                    capital_usdt += revenue * (1-FEE_RATE)
                    entry_confidence_manager = self.confidence_managers.get(current_params.get('entry_regime'))
                    if entry_confidence_manager: entry_confidence_manager.update(pnl_pct)
                    
                    in_position, trading_btc, last_used_params = False, 0.0, {}
                    trade_executed_this_step = 1; trade_type_this_step = 'TRADE'

                elif position_phase == 'INITIAL' and price >= buy_price * (1 + current_params.get('profit_threshold', 0.01) / 2):
                    position_phase = 'TRAILING'
                    current_stop_price = max(current_stop_price, buy_price * (1 + (FEE_RATE * 2)))
                
                elif position_phase == 'TRAILING':
                    trailing_stop_multiplier = current_params.get('trailing_stop_multiplier', 1.5)
                    stop_loss_atr_multiplier = current_params.get('stop_loss_atr_multiplier', 2.5)
                    new_trailing_stop = highest_price_in_trade - (row['atr'] * stop_loss_atr_multiplier * trailing_stop_multiplier)
                    current_stop_price = max(current_stop_price, new_trailing_stop)

            if not in_position:
                # Prioridade 1: Buscar um sinal de trade
                if model and row['volume'] >= row['volume_sma_50']:
                    features_for_prediction = pd.DataFrame(row[self.model_feature_names]).T
                    scaled_features = scaler.transform(features_for_prediction)
                    buy_confidence = model.predict_proba(scaled_features)[0][1]
                    
                    if buy_confidence > confidence_manager.get_confidence():
                        # ... (lógica de agressividade e cálculo do tamanho do trade, igual à versão 6.0) ...
                        base_risk = params.get('risk_per_trade_pct', 0.05)
                        signal_strength = (buy_confidence - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence()) if (1.0 - confidence_manager.get_confidence()) > 0 else 1.0
                        aggression_exponent = params.get('aggression_exponent', 2.0)
                        max_risk_scale = params.get('max_risk_scale', 3.0)
                        min_risk_scale = params.get('min_risk_scale', 0.5)
                        aggression_factor = min_risk_scale + (signal_strength ** aggression_exponent) * (max_risk_scale - min_risk_scale)
                        dynamic_risk_pct = base_risk * aggression_factor
                        trade_size_usdt = capital_usdt * dynamic_risk_pct
                        
                        # ... (lógica de dampener de volatilidade) ...
                        
                        if capital_usdt > 10 and trade_size_usdt > 10:
                            buy_price_eff = price * (1 + SLIPPAGE_RATE)
                            cost_of_trade = trade_size_usdt * (1 + FEE_RATE)
                            if capital_usdt >= cost_of_trade:
                                amount_to_buy_btc = trade_size_usdt / buy_price_eff
                                
                                in_position, trade_signal_found = True, True
                                trading_btc = amount_to_buy_btc
                                capital_usdt -= cost_of_trade
                                buy_price, highest_price_in_trade = buy_price_eff, buy_price_eff
                                current_stop_price = buy_price_eff - (row['atr'] * params.get('stop_loss_atr_multiplier', 2.5))
                                position_phase = 'INITIAL'
                                last_used_params = {**params, 'entry_regime': regime}
                                trade_executed_this_step = 1; trade_type_this_step = 'TRADE'
                
                # <<< MUDANÇA 3: REPLICAR A LÓGICA DE DCA NO QUICKTESTER >>>
                # Prioridade 2: Se não houve trade, verificar DCA
                if not trade_signal_found and DCA_IN_BEAR_MARKET_ENABLED and regime in ['BEAR_CALMO', 'BEAR_VOLATIL']:
                    if last_dca_time is None or (date - last_dca_time) >= timedelta(hours=24):
                        if capital_usdt >= DCA_MIN_CAPITAL_USDT:
                            cost_of_dca = DCA_DAILY_AMOUNT_USDT * (1 + FEE_RATE)
                            if capital_usdt >= cost_of_dca:
                                buy_price_eff = price * (1 + SLIPPAGE_RATE)
                                qty_bought = DCA_DAILY_AMOUNT_USDT / buy_price_eff
                                
                                capital_usdt -= cost_of_dca
                                long_term_btc_holdings += qty_bought
                                last_dca_time = date
                                
                                trade_executed_this_step = 1; trade_type_this_step = 'DCA'
                                logger.debug(f"Simulando DCA em {date}: Compra de {qty_bought:.8f} BTC.")

            total_portfolio_value = capital_usdt + (trading_btc * price) + (long_term_btc_holdings * price)
            portfolio_history.append({
                'timestamp': date, 
                'total_value': total_portfolio_value, 
                'trade_executed': trade_executed_this_step,
                'trade_type': trade_type_this_step
            })

        test_period_days = max(1, (test_features_df.index[-1] - test_features_df.index[0]).days)
        self.generate_report(portfolio_history, test_period_days, buy_and_hold_return, long_term_btc_holdings)