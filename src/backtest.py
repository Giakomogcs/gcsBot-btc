# src/backtest.py (VERSÃO 2.0 - COM ESTRATÉGIA MULTI-CAMADA E MÉTRICAS AVANÇADAS)

import numpy as np
import pandas as pd
from src.logger import logger
from src.confidence_manager import AdaptiveConfidenceManager

# --- Constantes de Custo Operacional ---
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005

def run_backtest(model, scaler, test_data_with_features: pd.DataFrame, strategy_params: dict, feature_names: list):
    """
    Executa um backtest realista com a Estratégia Multi-Camada:
    - Camada 1: Filtro de Regime de Mercado para ajuste de risco.
    - Camada 2: Sinais de ML com confiança adaptativa.
    - Camada 3: Gestão de Posição (Breakeven, Realização Parcial, Trailing Stop).
    - Extra: Simula a criação de um "Tesouro de BTC" com parte dos lucros.
    """
    # --- PARÂMETROS DE SIMULAÇÃO ---
    initial_capital = 100.0
    capital = initial_capital
    long_term_btc_holdings = 0.0 # Nosso "Tesouro de BTC"
    
    # --- PARÂMETROS DA ESTRATÉGIA (com valores padrão) ---
    base_risk_per_trade = strategy_params.get('risk_per_trade_pct', 0.05)
    profit_threshold = strategy_params.get('profit_threshold', 0.04)
    stop_loss_threshold = strategy_params.get('stop_loss_threshold', 0.02)
    trailing_stop_pct = stop_loss_threshold * 1.5 # Ex: trailing stop de 3% se o stop loss for 2%
    partial_sell_pct = 0.5 # Vende 50% da posição na realização parcial
    treasury_allocation_pct = 0.20 # 20% do lucro vai para o Tesouro de BTC
    
    # --- VARIÁVEIS DE ESTADO DO TRADE ---
    in_position = False
    buy_price = 0.0
    btc_amount = 0.0
    position_phase = None # Ex: 'INITIAL', 'BREAKEVEN', 'TRAILING'
    current_stop_price = 0.0
    highest_price_in_trade = 0.0

    # --- MÉTRICAS DE PERFORMANCE ---
    trade_count = 0
    portfolio_values = [{'timestamp': test_data_with_features.index[0], 'value': initial_capital}]

    # --- PREPARAÇÃO DAS FEATURES E PREDIÇÕES ---
    # Garante que todas as colunas de features existam
    for col in feature_names:
        if col not in test_data_with_features.columns:
            test_data_with_features[col] = 0
            
    X_test_features = test_data_with_features[feature_names].fillna(0)
    X_test_scaled_np = scaler.transform(X_test_features)
    predictions_proba = model.predict_proba(X_test_scaled_np)
    predictions_buy_proba = pd.Series(predictions_proba[:, 1], index=X_test_features.index)

    # --- INICIALIZAÇÃO DO GERENCIADOR DE CONFIANÇA ---
    initial_conf = strategy_params.get('initial_confidence', 0.6)
    confidence_manager = AdaptiveConfidenceManager(initial_confidence=initial_conf)

    # --- LOOP PRINCIPAL DO BACKTEST ---
    for date, row in test_data_with_features.iterrows():
        price = row['close']
        
        # --- CAMADA 1: O GENERAL (FILTRO DE REGIME DE MERCADO) ---
        regime = row.get('market_regime', 'LATERAL')
        is_trading_allowed = True
        current_base_risk = base_risk_per_trade

        if regime == 'BEAR':
            is_trading_allowed = False
        elif regime == 'RECUPERACAO':
            current_base_risk /= 2 # Reduz o risco pela metade
        elif regime == 'LATERAL':
            current_base_risk /= 4 # Reduz o risco a 1/4

        # --- LÓGICA DE GESTÃO DA POSIÇÃO ATIVA ---
        if in_position:
            # --- CAMADA 3: O SOLDADO (GESTÃO DA POSIÇÃO) ---
            highest_price_in_trade = max(highest_price_in_trade, price)

            # 1. Verificação do Stop Loss
            if price <= current_stop_price:
                # VENDA POR STOP LOSS
                sell_price = price * (1 - SLIPPAGE_RATE)
                capital += (btc_amount * sell_price) * (1 - FEE_RATE)
                pnl = (sell_price / buy_price) - 1
                confidence_manager.update(pnl) # O cérebro aprende com a perda
                in_position, btc_amount, trade_count = False, 0.0, trade_count + 1
            
            # 2. Lógica de Fases da Posição
            elif position_phase == 'INITIAL':
                # Checa se pode mover o stop para o breakeven
                if price >= buy_price * (1 + stop_loss_threshold):
                    position_phase = 'BREAKEVEN'
                    current_stop_price = buy_price * (1 + (FEE_RATE * 2)) # Ponto de equilíbrio + taxas
            
            elif position_phase == 'BREAKEVEN':
                # Checa se pode fazer a realização parcial
                if price >= buy_price * (1 + profit_threshold):
                    # VENDA PARCIAL
                    amount_to_sell = btc_amount * partial_sell_pct
                    sell_price = price * (1 - SLIPPAGE_RATE)
                    
                    revenue = (amount_to_sell * sell_price) * (1 - FEE_RATE)
                    profit_usdt = (sell_price - buy_price) * amount_to_sell
                    
                    # Alocação para o Tesouro de BTC
                    treasury_usdt = profit_usdt * treasury_allocation_pct
                    long_term_btc_holdings += treasury_usdt / price # Compra BTC para o tesouro
                    
                    # O restante do lucro e o capital inicial voltam para a conta de trading
                    capital += revenue - treasury_usdt
                    
                    btc_amount -= amount_to_sell
                    position_phase = 'TRAILING' # Move para a fase final
                    
            elif position_phase == 'TRAILING':
                # Atualiza o Trailing Stop
                new_trailing_stop = highest_price_in_trade * (1 - trailing_stop_pct)
                current_stop_price = max(current_stop_price, new_trailing_stop) # O stop só sobe, nunca desce

        # --- LÓGICA DE ENTRADA ---
        if not in_position and is_trading_allowed:
            # --- CAMADA 2: O CAPITÃO (SINAL DE ENTRADA) ---
            current_confidence_threshold = confidence_manager.get_confidence()
            conviction = predictions_buy_proba.get(date, 0)

            if conviction > current_confidence_threshold:
                signal_strength = (conviction - current_confidence_threshold) / (1.0 - current_confidence_threshold)
                dynamic_risk_pct = current_base_risk * (0.5 + signal_strength)
                trade_size_usdt = capital * dynamic_risk_pct
                
                if capital > 10 and trade_size_usdt > 10:
                    # COMPRA
                    buy_price_eff = price * (1 + SLIPPAGE_RATE)
                    amount_to_buy_btc = trade_size_usdt / buy_price_eff
                    fee = trade_size_usdt * FEE_RATE

                    # Inicia a posição e define as variáveis de estado
                    in_position = True
                    btc_amount = amount_to_buy_btc
                    capital -= (trade_size_usdt + fee)
                    buy_price = buy_price_eff
                    current_stop_price = buy_price * (1 - stop_loss_threshold)
                    highest_price_in_trade = buy_price
                    position_phase = 'INITIAL'

        # Atualiza o valor do portfólio no final de cada vela
        current_portfolio_value = capital + (btc_amount * price)
        portfolio_values.append({'timestamp': date, 'value': current_portfolio_value})

    # --- LIQUIDAÇÃO E CÁLCULO FINAL DE MÉTRICAS ---
    final_capital = portfolio_values[-1]['value']
    
    if len(portfolio_values) < 2:
        return 0.0, -1.0, -1.0, 0 # Retorno, Drawdown, Trades

    portfolio_df = pd.DataFrame(portfolio_values).set_index('timestamp')
    
    # 1. Cálculo do Retorno Anualizado
    total_return = (final_capital / initial_capital) - 1
    duration_days = (portfolio_df.index[-1] - portfolio_df.index[0]).days
    if duration_days < 1: duration_days = 1
    annualized_return = ((1 + total_return) ** (365.0 / duration_days)) - 1
    
    # 2. Cálculo do Máximo Drawdown
    running_max = portfolio_df['value'].cummax()
    drawdown = (portfolio_df['value'] - running_max) / running_max
    max_drawdown = drawdown.min()

    logger.debug(
        f"Backtest Concluído. Capital Final: {final_capital:.2f}, "
        f"Retorno Anualizado: {annualized_return:+.2%}, Max Drawdown: {max_drawdown:.2%}, Trades: {trade_count}"
    )

    # Retorna as métricas necessárias para o Calmar Ratio e a penalidade de trade
    return final_capital, annualized_return, max_drawdown, trade_count