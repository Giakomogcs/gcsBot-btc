# src/backtest.py (VERSÃO 5.0 - LÓGICA DE EXECUÇÃO ROBUSTA)

import numpy as np
import pandas as pd

from src.config import FEE_RATE, SLIPPAGE_RATE 
from src.confidence_manager import AdaptiveConfidenceManager

def calculate_sortino_ratio(series, periods_per_year=365*24*60):
    """Calcula o Sortino Ratio a partir de uma série de valores de portfólio."""
    returns = series.pct_change().dropna()
    
    # --- MUDANÇA --- Usando um target return de 0 para simplificar
    target_return = 0
    downside_returns = returns[returns < target_return]
    
    expected_return = returns.mean()
    downside_std = downside_returns.std()
    
    if downside_std == 0 or pd.isna(downside_std):
        return 0.0
        
    sortino = (expected_return * periods_per_year) / (downside_std * np.sqrt(periods_per_year))
    return sortino if not pd.isna(sortino) else 0.0


def run_backtest(model, scaler, test_data_with_features: pd.DataFrame, strategy_params: dict, feature_names: list):
    """
    Executa um backtest realista e robusto, com lógica de risco avançada,
    e retorna um conjunto completo de métricas de performance.
    """
    initial_capital = 100.0
    capital_usdt = initial_capital
    trading_btc = 0.0
    treasury_btc = 0.0
    
    portfolio_history = []
    trade_pnls = [] # --- NOVO --- Para calcular o Profit Factor

    # --- NOVO --- Carregando todos os novos hiperparâmetros
    base_risk = strategy_params.get('risk_per_trade_pct', 0.05)
    profit_threshold = strategy_params.get('profit_threshold', 0.01)
    # stop_loss_threshold foi substituído pelo multiplicador de ATR
    stop_loss_atr_multiplier = strategy_params.get('stop_loss_atr_multiplier', 2.5)
    
    trailing_stop_multiplier = strategy_params.get('trailing_stop_multiplier', 1.5)
    partial_sell_pct = strategy_params.get('partial_sell_pct', 0.5)
    treasury_allocation_pct = strategy_params.get('treasury_allocation_pct', 0.20)

    # Parâmetros para a lógica de risco agressiva
    aggression_exponent = strategy_params.get('aggression_exponent', 2.0)
    max_risk_scale = strategy_params.get('max_risk_scale', 3.0)
    min_risk_scale = 0.5 # Fixo
    
    # --- Variáveis de estado do trade ---
    in_position = False
    buy_price = 0.0
    position_phase = None 
    current_stop_price = 0.0
    highest_price_in_trade = 0.0
    
    # --- Preparação das Features e Predições ---
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
        
        regime = row.get('market_regime', 'LATERAL')
        current_base_risk = base_risk
        if regime == 'BEAR':
            is_trading_allowed = False
        else:
            is_trading_allowed = True
            if regime == 'RECUPERACAO': current_base_risk /= 2
            elif regime == 'LATERAL': current_base_risk /= 3

        if in_position:
            highest_price_in_trade = max(highest_price_in_trade, price)

            if price <= current_stop_price:
                sell_price = price * (1 - SLIPPAGE_RATE)
                pnl = (trading_btc * sell_price) - (trading_btc * buy_price)
                trade_pnls.append(pnl) # Adiciona o resultado do trade
                capital_usdt += (trading_btc * sell_price) * (1 - FEE_RATE)
                pnl_pct = (sell_price / buy_price) - 1
                confidence_manager.update(pnl_pct)
                in_position, trading_btc = False, 0.0
            
            # --- MUDANÇA --- Lógica de Trailing Stop agora baseada em ATR
            elif position_phase == 'TRAILING':
                # O trailing stop segue o preço máximo com uma distância baseada no ATR
                new_trailing_stop = highest_price_in_trade - (row['atr'] * stop_loss_atr_multiplier * trailing_stop_multiplier)
                current_stop_price = max(current_stop_price, new_trailing_stop)

        if not in_position and is_trading_allowed:
            # --- NOVO: FILTRO DE VOLUME ---
            if row['volume'] < row['volume_sma_50']:
                pass # Pula a lógica de entrada se o volume for baixo
            else:
                conviction = predictions_buy_proba.get(date, 0)
                if conviction > confidence_manager.get_confidence():
                    # --- NOVA LÓGICA DE RISCO AGRESSIVO ---
                    signal_strength = (conviction - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence())
                    aggression_factor = min_risk_scale + (signal_strength ** aggression_exponent) * (max_risk_scale - min_risk_scale)
                    dynamic_risk_pct = current_base_risk * aggression_factor
                    trade_size_usdt = capital_usdt * dynamic_risk_pct

                    # --- NOVO: AJUSTE DE RISCO PELA VOLATILIDADE ---
                    current_atr = row.get('atr', 0)
                    long_term_atr = row.get('atr_long_avg', current_atr)
                    if long_term_atr > 0 and current_atr > 0:
                        volatility_factor = current_atr / long_term_atr
                        risk_dampener = np.clip(1 / volatility_factor, 0.6, 1.2)
                        trade_size_usdt *= risk_dampener
                    # -----------------------------------------------

                    if capital_usdt > 10 and trade_size_usdt > 10:
                        buy_price_eff = price * (1 + SLIPPAGE_RATE)
                        amount_to_buy_btc = trade_size_usdt / buy_price_eff
                        
                        in_position = True
                        trading_btc = amount_to_buy_btc
                        capital_usdt -= trade_size_usdt * (1 + FEE_RATE)
                        buy_price = buy_price_eff
                        
                        # --- MUDANÇA: STOP LOSS BASEADO EM ATR ---
                        current_stop_price = buy_price_eff - (row['atr'] * stop_loss_atr_multiplier)
                        # -------------------------------------------
                        
                        highest_price_in_trade = buy_price
                        position_phase = 'INITIAL' # Simplificado para o backtest de otimização

        trading_value = capital_usdt + (trading_btc * price)
        treasury_value = treasury_btc * price
        total_portfolio_value = trading_value + treasury_value
        
        portfolio_history.append({'timestamp': date, 'total_value': total_portfolio_value})

    # --- CÁLCULO FINAL DE MÉTRICAS AVANÇADAS ---
    if len(portfolio_history) < 2:
        return 0.0, 0.0, -1.0, 0, 0.0, 0.0, 0.0 # Retorna zeros para todas as métricas

    portfolio_df = pd.DataFrame(portfolio_history).set_index('timestamp')
    
    # Métricas básicas
    final_value = portfolio_df['total_value'].iloc[-1]
    total_return = (final_value / initial_capital) - 1
    duration_days = (portfolio_df.index[-1] - portfolio_df.index[0]).days
    if duration_days < 1: duration_days = 1
    annualized_return = ((1 + total_return) ** (365.0 / duration_days)) - 1
    running_max = portfolio_df['total_value'].cummax()
    drawdown = (portfolio_df['total_value'] - running_max) / running_max
    max_drawdown = drawdown.min()
    trade_count = len(trade_pnls)

    # --- NOVO: Cálculo do Profit Factor e Sortino Ratio ---
    trade_pnls = np.array(trade_pnls)
    total_profit = trade_pnls[trade_pnls > 0].sum()
    total_loss = abs(trade_pnls[trade_pnls < 0].sum())
    profit_factor = total_profit / total_loss if total_loss > 0 else 100.0

    sortino_ratio = calculate_sortino_ratio(portfolio_df['total_value'])
    
    # --- MUDANÇA --- Retornando todas as novas métricas
    return (
        final_value,
        annualized_return,
        max_drawdown,
        trade_count,
        sortino_ratio,
        profit_factor,
        np.mean(trade_pnls) if trade_count > 0 else 0.0
    )