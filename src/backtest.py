# src/backtest.py (VERSÃO 4.0 - SIMULAÇÃO COM TESOURARIA INTEGRADA)

import numpy as np
import pandas as pd

from src.config import FEE_RATE, SLIPPAGE_RATE 
from src.confidence_manager import AdaptiveConfidenceManager

def run_backtest(model, scaler, test_data_with_features: pd.DataFrame, strategy_params: dict, feature_names: list):
    """
    Executa um backtest realista, com a performance total refletindo tanto
    o capital de trading (USDT) quanto a tesouraria de longo prazo (BTC).
    """
    ### PASSO 1: Inicializar o estado do portfólio completo ###
    initial_capital = 100.0
    capital_usdt = initial_capital
    trading_btc = 0.0
    treasury_btc = 0.0 # Tesouraria de BTC de longo prazo
    
    # Histórico para métricas de performance
    portfolio_history = []
    trade_count = 0

    # --- Carregar TODOS os parâmetros da estratégia do dicionário otimizado ---
    # Usar .get() fornece um valor padrão seguro se a chave não for encontrada
    base_risk = strategy_params.get('risk_per_trade_pct', 0.05)
    profit_threshold = strategy_params.get('profit_threshold', 0.01)
    stop_loss_threshold = strategy_params.get('stop_loss_threshold', 0.005)
    
    trailing_stop_multiplier = strategy_params.get('trailing_stop_multiplier', 1.5)
    partial_sell_pct = strategy_params.get('partial_sell_pct', 0.5)
    treasury_allocation_pct = strategy_params.get('treasury_allocation_pct', 0.20)
    
    # --- Variáveis de estado do trade ---
    in_position = False
    buy_price = 0.0
    position_phase = None # 'INITIAL', 'BREAKEVEN', 'TRAILING'
    current_stop_price = 0.0
    highest_price_in_trade = 0.0

    # --- Preparação das Features e Predições ---
    # Garante que todas as colunas de features existam no dataframe de teste
    for col in feature_names:
        if col not in test_data_with_features.columns:
            test_data_with_features[col] = 0
            
    X_test_features = test_data_with_features[feature_names].fillna(0)
    X_test_scaled = pd.DataFrame(scaler.transform(X_test_features), index=X_test_features.index, columns=X_test_features.columns)
    
    # Obter a probabilidade da classe "1" (compra)
    predictions_buy_proba = pd.Series(model.predict_proba(X_test_scaled)[:, 1], index=X_test_features.index)

    ### PASSO 2: Inicializar o ConfidenceManager com todos os parâmetros otimizáveis ###
    confidence_manager = AdaptiveConfidenceManager(
        initial_confidence=strategy_params.get('initial_confidence', 0.6),
        learning_rate=strategy_params.get('confidence_learning_rate', 0.05),
        window_size=strategy_params.get('confidence_window_size', 5) # Novo parâmetro!
    )

    # --- Loop Principal do Backtest ---
    for date, row in test_data_with_features.iterrows():
        price = row['close']
        
        # Ajuste de risco baseado no regime de mercado
        regime = row.get('market_regime', 'LATERAL')
        current_base_risk = base_risk
        if regime == 'BEAR':
            is_trading_allowed = False
        else:
            is_trading_allowed = True
            if regime == 'RECUPERACAO': current_base_risk /= 2
            elif regime == 'LATERAL': current_base_risk /= 3

        # --- Gerenciamento de Posição Ativa ---
        if in_position:
            highest_price_in_trade = max(highest_price_in_trade, price)

            # 1. Checagem de Stop Loss (Total ou Trailing)
            if price <= current_stop_price:
                sell_price = price * (1 - SLIPPAGE_RATE)
                capital_usdt += (trading_btc * sell_price) * (1 - FEE_RATE)
                pnl = (sell_price / buy_price) - 1
                confidence_manager.update(pnl)
                in_position, trading_btc = False, 0.0
                trade_count += 1
            
            # 2. Gerenciamento de Fases do Trade
            elif position_phase == 'INITIAL' and price >= buy_price * (1 + stop_loss_threshold):
                position_phase = 'BREAKEVEN'
                current_stop_price = buy_price * (1 + (FEE_RATE * 2)) # Ponto de equilíbrio
            
            elif position_phase == 'BREAKEVEN' and price >= buy_price * (1 + profit_threshold):
                amount_to_sell = trading_btc * partial_sell_pct
                sell_price = price * (1 - SLIPPAGE_RATE)
                revenue = (amount_to_sell * sell_price) * (1 - FEE_RATE)
                profit_usdt = (sell_price - buy_price) * amount_to_sell

                if profit_usdt > 0:
                    treasury_usdt = profit_usdt * treasury_allocation_pct
                    treasury_btc += treasury_usdt / price
                    capital_usdt += revenue - treasury_usdt
                else:
                    capital_usdt += revenue
                    
                trading_btc -= amount_to_sell
                position_phase = 'TRAILING'
                
            elif position_phase == 'TRAILING':
                new_trailing_stop = highest_price_in_trade * (1 - (stop_loss_threshold * trailing_stop_multiplier))
                current_stop_price = max(current_stop_price, new_trailing_stop)

        # --- Verificação de Nova Entrada ---
        if not in_position and is_trading_allowed:
            conviction = predictions_buy_proba.get(date, 0)
            if conviction > confidence_manager.get_confidence():
                signal_strength = (conviction - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence())
                dynamic_risk_pct = current_base_risk * (0.5 + signal_strength * 1.5) # Amplifica o efeito do sinal
                trade_size_usdt = capital_usdt * dynamic_risk_pct
                
                if capital_usdt > 10 and trade_size_usdt > 10: # Limites práticos
                    buy_price_eff = price * (1 + SLIPPAGE_RATE)
                    amount_to_buy_btc = trade_size_usdt / buy_price_eff
                    fee = trade_size_usdt * FEE_RATE
                    
                    in_position = True
                    trading_btc = amount_to_buy_btc
                    capital_usdt -= (trade_size_usdt + fee)
                    buy_price = buy_price_eff
                    current_stop_price = buy_price * (1 - stop_loss_threshold)
                    highest_price_in_trade = buy_price
                    position_phase = 'INITIAL'

        ### PASSO 3: Calcular o VALOR TOTAL do portfólio (Trading + Tesouraria) ###
        trading_value = capital_usdt + (trading_btc * price)
        treasury_value = treasury_btc * price
        total_portfolio_value = trading_value + treasury_value
        
        portfolio_history.append({
            'timestamp': date, 
            'total_value': total_portfolio_value,
            'treasury_btc': treasury_btc
        })

    # --- Cálculo Final de Métricas ---
    if len(portfolio_history) < 2:
        return 0.0, -1.0, -1.0, 0, 0.0

    portfolio_df = pd.DataFrame(portfolio_history).set_index('timestamp')
    final_value = portfolio_df['total_value'].iloc[-1]
    final_treasury_btc = portfolio_df['treasury_btc'].iloc[-1]
    
    total_return = (final_value / initial_capital) - 1
    
    duration_days = (portfolio_df.index[-1] - portfolio_df.index[0]).days
    if duration_days < 1: duration_days = 1
    annualized_return = ((1 + total_return) ** (365.0 / duration_days)) - 1
    
    running_max = portfolio_df['total_value'].cummax()
    drawdown = (portfolio_df['total_value'] - running_max) / running_max
    max_drawdown = drawdown.min()

    # Este módulo não loga mais; ele apenas retorna os resultados.
    # O Optimizer será responsável por logar o resultado de cada backtest.
    return final_value, annualized_return, max_drawdown, trade_count, final_treasury_btc