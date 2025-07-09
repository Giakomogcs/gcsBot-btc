# src/backtest.py (VERSÃO 6.1 - Simulação de Tesouraria)

import numpy as np
import pandas as pd

from src.config import FEE_RATE, SLIPPAGE_RATE 
from src.confidence_manager import AdaptiveConfidenceManager

def calculate_sortino_ratio(series, periods_per_year=365*24*60):
    if len(series) < 2:
        return 0.0
    returns = series.pct_change().dropna()
    if len(returns) < 2:
        return 0.0
        
    target_return = 0
    downside_returns = returns[returns < target_return]
    
    expected_return = returns.mean()
    downside_std = downside_returns.std()
    
    if downside_std == 0 or pd.isna(downside_std) or downside_std < 1e-9:
        return 100.0 if expected_return > 0 else 0.0
        
    sortino = (expected_return * periods_per_year) / (downside_std * np.sqrt(periods_per_year))
    return sortino if not pd.isna(sortino) else 0.0


def run_backtest(model, scaler, test_data_with_features: pd.DataFrame, strategy_params: dict, feature_names: list):
    initial_capital = 100.0
    capital_usdt = initial_capital
    trading_btc = 0.0
    
    # <<< MUDANÇA 1: ADICIONAR A TESOURARIA À SIMULAÇÃO >>>
    # O valor total do portfólio agora deve considerar o BTC guardado.
    long_term_btc_holdings = 0.0
    
    portfolio_history = []
    trade_pnls = []

    # Parâmetros são recebidos e usados diretamente, sem modificação interna
    base_risk = strategy_params.get('risk_per_trade_pct', 0.05)
    stop_loss_atr_multiplier = strategy_params.get('stop_loss_atr_multiplier', 2.5)
    trailing_stop_multiplier = strategy_params.get('trailing_stop_multiplier', 1.5)
    aggression_exponent = strategy_params.get('aggression_exponent', 2.0)
    max_risk_scale = strategy_params.get('max_risk_scale', 3.0)
    min_risk_scale = strategy_params.get('min_risk_scale', 0.5)
    profit_threshold = strategy_params.get('profit_threshold', 0.015) # Adicionado para o trailing
    treasury_allocation_pct = strategy_params.get('treasury_allocation_pct', 0.20) # Novo parâmetro
    
    in_position = False
    buy_price = 0.0
    position_phase = None 
    current_stop_price = 0.0
    highest_price_in_trade = 0.0
    
    for col in feature_names:
        if col not in test_data_with_features.columns:
            test_data_with_features[col] = 0
            
    X_test_features = test_data_with_features[feature_names].fillna(0)
    X_test_scaled = pd.DataFrame(scaler.transform(X_test_features), index=X_test_features.index, columns=X_test_features.columns)
    predictions_buy_proba = pd.Series(model.predict_proba(X_test_scaled)[:, 1], index=X_test_features.index)

    confidence_manager = AdaptiveConfidenceManager(
        initial_confidence=strategy_params.get('initial_confidence', 0.6),
        learning_rate=strategy_params.get('confidence_learning_rate', 0.05),
        window_size=strategy_params.get('confidence_window_size', 5)
    )

    # --- Loop Principal do Backtest ---
    for date, row in test_data_with_features.iterrows():
        price = row['close']
        
        if in_position:
            highest_price_in_trade = max(highest_price_in_trade, price)

            if price <= current_stop_price:
                sell_price = price * (1 - SLIPPAGE_RATE)
                
                # <<< MUDANÇA 2: SIMULAR A LÓGICA COMPLETA DE VENDA >>>
                revenue_usdt = (trading_btc * sell_price) * (1 - FEE_RATE)
                pnl_usdt = revenue_usdt - (trading_btc * buy_price)
                trade_pnls.append(pnl_usdt)
                pnl_pct = (sell_price / buy_price) - 1 if buy_price > 0 else 0
                
                reinvested_usdt = revenue_usdt
                if pnl_usdt > 0:
                    treasury_usdt = pnl_usdt * treasury_allocation_pct
                    reinvested_usdt -= treasury_usdt
                    long_term_btc_holdings += treasury_usdt / price if price > 0 else 0

                capital_usdt += reinvested_usdt
                confidence_manager.update(pnl_pct)
                in_position, trading_btc = False, 0.0
            
            # Movido para ser checado em cada step enquanto em posição
            elif position_phase == 'INITIAL' and price >= buy_price * (1 + profit_threshold / 2):
                position_phase = 'TRAILING'
                current_stop_price = max(current_stop_price, buy_price * (1 + (FEE_RATE + SLIPPAGE_RATE)))

            elif position_phase == 'TRAILING':
                new_trailing_stop = highest_price_in_trade * (1 - (row['atr']/price * stop_loss_atr_multiplier * trailing_stop_multiplier))
                current_stop_price = max(current_stop_price, new_trailing_stop)


        if not in_position:
            if row['volume'] < row['volume_sma_50']:
                pass 
            else:
                conviction = predictions_buy_proba.get(date, 0)
                if conviction > confidence_manager.get_confidence():
                    signal_strength = (conviction - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence()) if (1.0 - confidence_manager.get_confidence()) > 0 else 1.0
                    aggression_factor = min_risk_scale + (signal_strength ** aggression_exponent) * (max_risk_scale - min_risk_scale)
                    
                    dynamic_risk_pct = base_risk * aggression_factor
                    trade_size_usdt = capital_usdt * dynamic_risk_pct

                    current_atr = row.get('atr', 0)
                    long_term_atr = row.get('atr_long_avg', current_atr)
                    if long_term_atr > 0 and current_atr > 0:
                        volatility_factor = current_atr / long_term_atr
                        risk_dampener = np.clip(1 / volatility_factor, 0.6, 1.2)
                        trade_size_usdt *= risk_dampener

                    if capital_usdt > 10 and trade_size_usdt > 10:
                        buy_price_eff = price * (1 + SLIPPAGE_RATE)
                        # O custo do trade (incluindo taxa) é deduzido do capital
                        cost_of_trade = trade_size_usdt * (1 + FEE_RATE)
                        if capital_usdt >= cost_of_trade:
                            amount_to_buy_btc = trade_size_usdt / buy_price_eff
                            
                            in_position = True
                            trading_btc = amount_to_buy_btc
                            capital_usdt -= cost_of_trade
                            buy_price = buy_price_eff
                            
                            current_stop_price = buy_price_eff - (row['atr'] * stop_loss_atr_multiplier)
                            
                            highest_price_in_trade = buy_price
                            position_phase = 'INITIAL'

        # <<< MUDANÇA 3: CÁLCULO CORRETO DO VALOR TOTAL DO PORTFÓLIO >>>
        # O valor total agora inclui o capital, a posição aberta e a tesouraria.
        total_portfolio_value = capital_usdt + (trading_btc * price) + (long_term_btc_holdings * price)
        portfolio_history.append({'timestamp': date, 'total_value': total_portfolio_value})

    if len(trade_pnls) == 0:
        return 100.0, 0.0, -1.0, 0, 0.0, 0.0, 0.0

    portfolio_df = pd.DataFrame(portfolio_history).set_index('timestamp')
    
    final_value = portfolio_df['total_value'].iloc[-1]
    total_return = (final_value / initial_capital) - 1
    duration_days = max(1, (portfolio_df.index[-1] - portfolio_df.index[0]).days)
    annualized_return = ((1 + total_return) ** (365.0 / duration_days)) - 1
    
    running_max = portfolio_df['total_value'].cummax()
    drawdown = (portfolio_df['total_value'] - running_max) / running_max
    max_drawdown = drawdown.min()
    
    trade_count = len(trade_pnls)
    trade_pnls_np = np.array(trade_pnls)
    total_profit = trade_pnls_np[trade_pnls_np > 0].sum()
    total_loss = abs(trade_pnls_np[trade_pnls_np < 0].sum())
    profit_factor = total_profit / total_loss if total_loss > 0 else 100.0

    sortino_ratio = calculate_sortino_ratio(portfolio_df['total_value'])
    
    return (
        final_value,
        annualized_return,
        max_drawdown,
        trade_count,
        sortino_ratio,
        profit_factor,
        np.mean(trade_pnls_np) if trade_count > 0 else 0.0
    )