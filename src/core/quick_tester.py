# src/quick_tester.py (VERSÃO 7.1 - Final e Corrigido)

import json
import pandas as pd
import numpy as np
import joblib
import os
from datetime import datetime, timezone, timedelta

from src.logger import logger, log_table
from src.config import (
    MODEL_METADATA_FILE, SYMBOL, FEE_RATE, SLIPPAGE_RATE, IOF_RATE, DATA_DIR,
    DCA_IN_BEAR_MARKET_ENABLED, DCA_DAILY_AMOUNT_USDT, DCA_MIN_CAPITAL_USDT
)
from src.core.data_manager import DataManager
from src.core.confidence_manager import AdaptiveConfidenceManager
from src.core.backtest import calculate_sortino_ratio

class QuickTester:
    def __init__(self):
        self.data_manager = DataManager()
        self.models = {}
        self.scalers = {}
        self.strategy_params = {}
        self.confidence_managers = {}
        self.model_feature_names = []
        self.regime_map = {} # Mapeia um regime para o especialista que ele deve usar

    def _load_all_specialists(self):
        """
        Carrega todos os artefatos de modelo (especialistas e generalistas)
        com base no arquivo de metadados.
        """
        try:
            with open(MODEL_METADATA_FILE, 'r') as f:
                metadata = json.load(f)

            logger.info(f"✅ Metadados carregados. Verificando validade do modelo...")
            valid_until_dt = datetime.fromisoformat(metadata['valid_until'])
            if datetime.now(timezone.utc) > valid_until_dt:
                logger.warning(f"🚨 ALERTA: O CONJUNTO DE MODELOS EXPIROU EM {valid_until_dt.strftime('%Y-%m-%d')}! 🚨")
            
            self.model_feature_names = metadata['feature_names']
            summary = metadata.get('optimization_summary', {})
            
            loaded_specialists_count = 0
            for regime, result in summary.items():
                specialist_to_load = regime
                # Se o regime usa um fallback, aponta para o modelo generalista correto
                if result.get('status') == 'Fallback to Generalist':
                    specialist_to_load = result['fallback_model']
                
                self.regime_map[regime] = specialist_to_load
                
                # Carrega o especialista apenas se ele ainda não foi carregado
                if specialist_to_load and specialist_to_load not in self.models:
                    try:
                        final_spec_info = summary.get(specialist_to_load, {})
                        if final_spec_info.get('status') == 'Optimized and Saved':
                            model_path = os.path.join(DATA_DIR, final_spec_info['model_file'])
                            scaler_path = os.path.join(DATA_DIR, final_spec_info['scaler_file'])
                            params_path = os.path.join(DATA_DIR, final_spec_info['params_file'])

                            self.models[specialist_to_load] = joblib.load(model_path)
                            self.scalers[specialist_to_load] = joblib.load(scaler_path)
                            with open(params_path, 'r') as p:
                                self.strategy_params[specialist_to_load] = json.load(p)
                            
                            loaded_specialists_count += 1
                    except Exception as e:
                        logger.error(f"Falha ao carregar artefatos para o especialista '{specialist_to_load}': {e}")

            if not self.models:
                logger.error("Nenhum especialista de trading foi carregado. Execute a otimização.")
                return False

            logger.info(f"✅ {loaded_specialists_count} especialista(s) únicos carregado(s). O mapeamento de regimes está pronto.")
            return True

        except Exception as e:
            logger.error(f"ERRO CRÍTICO ao carregar especialistas: {e}", exc_info=True)
            return False
    
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

        finance_summary = [
            ["Período Testado", f"{df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d} ({test_period_days} dias)"],
            ["Capital Inicial", f"${initial_capital:,.2f}"],
            ["Capital Final", f"💎 ${final_capital:,.2f}"],
            ["Resultado Total da Estratégia", f"📈 {total_return:+.2%}"],
            ["Retorno do Buy & Hold no Período", f"📊 {buy_and_hold_return:+.2%}"],
        ]
        performance_metrics = [
            ["Retorno Anualizado", f"{annualized_return:+.2%}"],
            ["Máximo Drawdown", f"📉 {max_drawdown:.2%}"],
            ["Sortino Ratio (Retorno/Risco)", f"🍀 {sortino_ratio:.2f}"],
            ["Calmar Ratio (Retorno/Drawdown)", f"{calmar_ratio:.2f}"],
        ]
        activity_summary = [
            ["Total de Trades de Lucro", f"{int(total_trades)}"],
            ["Total de Compras de Acumulação (DCA)", f"{int(total_dca)}"],
            ["Tesouraria Final (BTC Acumulado)", f"🏦 {final_treasury_btc:.8f} BTC"],
        ]

        log_table("🏆 RESUMO GERAL DA PERFORMANCE (OUT-OF-SAMPLE)", finance_summary, headers=["Métrica", "Valor"])
        log_table("Métricas de Performance", performance_metrics, headers=["Métrica", "Valor"])
        log_table("Atividade do Bot", activity_summary, headers=["Métrica", "Valor"])

    def run(self, start_date_str: str, end_date_str: str, initial_capital: float = 100.0):
        if not self._load_all_specialists(): return

        logger.info(f"Carregando e preparando dados para o período de teste: {start_date_str} a {end_date_str}...")
        full_data = self.data_manager.update_and_load_data(SYMBOL, '1m')
        
        # <<< CORREÇÃO CRÍTICA: USA OS DADOS DIRETAMENTE DO DATAMANAGER >>>
        test_data = full_data.loc[start_date_str:end_date_str].copy()
        
        if test_data.empty: 
            logger.error("Não há dados disponíveis para o período de teste."); return
        
        buy_and_hold_return = (test_data['close'].iloc[-1] / test_data['close'].iloc[0]) - 1
        
        capital_usdt, trading_btc, long_term_btc_holdings, last_dca_time = initial_capital, 0.0, 0.0, None
        in_position, buy_price, position_phase, current_stop_price, highest_price_in_trade = False, 0.0, None, 0.0, 0.0
        portfolio_history, last_used_params = [], {}
        
        logger.info("🚀 Iniciando simulação de trading (backtest) com especialistas...")
        for date, row in test_data.iterrows():
            price = row['close']
            trade_executed_this_step, trade_type_this_step = 0, None
            
            current_regime = row.get('market_regime', 'LATERAL_CALMO')
            specialist_name = self.regime_map.get(current_regime)
            
            if not specialist_name: # Pula a iteração se não houver especialista mapeado
                total_portfolio_value = capital_usdt + (trading_btc * price) + (long_term_btc_holdings * price)
                portfolio_history.append({'timestamp': date, 'total_value': total_portfolio_value, 'trade_executed': 0, 'trade_type': None})
                continue
            
            model = self.models.get(specialist_name)
            scaler = self.scalers.get(specialist_name)
            params = self.strategy_params.get(specialist_name)
            
            if specialist_name not in self.confidence_managers:
                self.confidence_managers[specialist_name] = AdaptiveConfidenceManager(**params)
            confidence_manager = self.confidence_managers.get(specialist_name)
            
            trade_signal_found = False
            if in_position:
                highest_price_in_trade = max(highest_price_in_trade, price)
                if price <= current_stop_price:
                    sell_price = price * (1 - SLIPPAGE_RATE)
                    revenue = trading_btc * sell_price
                    pnl_usdt = (revenue * (1-FEE_RATE)) - (buy_price * trading_btc * (1 + FEE_RATE + IOF_RATE))
                    pnl_pct = (sell_price / buy_price) - 1
                    if pnl_usdt > 0:
                        treasury_usdt = pnl_usdt * last_used_params.get('treasury_allocation_pct', 0.20)
                        revenue -= treasury_usdt
                        long_term_btc_holdings += treasury_usdt / price
                    capital_usdt += revenue
                    self.confidence_managers[last_used_params['entry_specialist']].update(pnl_pct)
                    in_position, trading_btc, last_used_params = False, 0.0, {}
                    trade_executed_this_step, trade_type_this_step = 1, 'TRADE'
                elif position_phase == 'INITIAL' and price >= buy_price * (1 + last_used_params.get('profit_threshold', 0.01) / 2):
                    position_phase = 'TRAILING'
                    current_stop_price = max(current_stop_price, buy_price * (1 + (FEE_RATE * 2)))
                elif position_phase == 'TRAILING':
                    new_trailing_stop = highest_price_in_trade - (row['atr'] * last_used_params.get('trailing_stop_multiplier', 1.5))
                    current_stop_price = max(current_stop_price, new_trailing_stop)

            if not in_position:
                if model and row['volume'] >= row['volume_sma_50']:
                    features_for_prediction = pd.DataFrame([row[self.model_feature_names]])
                    scaled_features = scaler.transform(features_for_prediction)
                    buy_confidence = model.predict_proba(scaled_features)[0][1]
                    
                    if buy_confidence > confidence_manager.get_confidence():
                        base_risk = params.get('risk_per_trade_pct', 0.05)
                        signal_strength = (buy_confidence - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence())
                        aggression_factor = params.get('min_risk_scale', 0.5) + (signal_strength ** params.get('aggression_exponent', 2.0)) * (params.get('max_risk_scale', 3.0) - params.get('min_risk_scale', 0.5))
                        trade_size_usdt = capital_usdt * (base_risk * aggression_factor)
                        
                        if capital_usdt > 10 and trade_size_usdt > 10:
                            buy_price_eff = price * (1 + SLIPPAGE_RATE)
                            cost_of_trade = trade_size_usdt * (1 + FEE_RATE + IOF_RATE)
                            if capital_usdt >= cost_of_trade:
                                amount_to_buy_btc = trade_size_usdt / buy_price_eff
                                in_position, trade_signal_found = True, True
                                trading_btc, capital_usdt = amount_to_buy_btc, capital_usdt - cost_of_trade
                                buy_price, highest_price_in_trade = buy_price_eff, buy_price_eff
                                current_stop_price = buy_price_eff - (row['atr'] * params.get('stop_loss_atr_multiplier', 2.5))
                                position_phase = 'INITIAL'
                                last_used_params = {**params, 'entry_specialist': specialist_name}
                                trade_executed_this_step, trade_type_this_step = 1, 'TRADE'
                
                if not trade_signal_found and DCA_IN_BEAR_MARKET_ENABLED and 'BEAR' in current_regime:
                    if last_dca_time is None or (date - last_dca_time) >= timedelta(hours=24):
                        if capital_usdt >= DCA_MIN_CAPITAL_USDT:
                            cost_of_dca = DCA_DAILY_AMOUNT_USDT * (1 + FEE_RATE)
                            if capital_usdt >= cost_of_dca:
                                qty_bought = DCA_DAILY_AMOUNT_USDT / (price * (1 + SLIPPAGE_RATE))
                                capital_usdt -= cost_of_dca
                                long_term_btc_holdings += qty_bought
                                last_dca_time = date
                                trade_executed_this_step, trade_type_this_step = 1, 'DCA'

            total_portfolio_value = capital_usdt + (trading_btc * price) + (long_term_btc_holdings * price)
            portfolio_history.append({'timestamp': date, 'total_value': total_portfolio_value, 'trade_executed': trade_executed_this_step, 'trade_type': trade_type_this_step})

        test_period_days = max(1, (test_data.index[-1] - test_data.index[0]).days)
        self.generate_report(portfolio_history, test_period_days, buy_and_hold_return, long_term_btc_holdings)