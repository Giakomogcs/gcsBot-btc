# src/backtest.py

import numpy as np
import pandas as pd
from src.logger import logger

# --- Constantes de Custo Operacional ---
# Taxa padrão da Binance para ordens a mercado (0.1%)
FEE_RATE = 0.001
# Estimativa de derrapagem (slippage) para ordens a mercado em um ativo líquido como BTC.
# Um valor conservador, mas realista.
SLIPPAGE_RATE = 0.0005

def run_backtest(model, scaler, test_data: pd.DataFrame, strategy_params: dict, feature_names: list):
    """
    Executa um backtest realista, incorporando taxas (fees) e derrapagem (slippage).
    Esta função é o "juiz" da otimização, fornecendo uma métrica de performance honesta.

    Args:
        model: O modelo de machine learning treinado.
        scaler: O normalizador de features (StandardScaler).
        test_data (pd.DataFrame): O conjunto de dados de teste.
        strategy_params (dict): Dicionário com 'profit_threshold', 'stop_loss_threshold', etc.
        feature_names (list): Lista com os nomes das features usadas no treino.

    Returns:
        float: O capital final após a simulação.
        float: O Sharpe Ratio anualizado da estratégia.
    """
    initial_capital = 100.0
    capital = initial_capital
    btc_amount = 0.0
    in_position = False
    buy_price = 0.0
    trade_count = 0
    portfolio_values = [initial_capital]

    # Prepara as features dos dados de teste.
    # O `model_trainer` já aplicou o .shift(1) para evitar look-ahead bias.
    X_test_full = test_data.copy()

    # Garante que as colunas de features existam, preenchendo com 0 se ausentes
    for col in feature_names:
        if col not in X_test_full.columns:
            X_test_full[col] = 0
            
    X_test_features = X_test_full[feature_names].fillna(0)
    X_test_scaled = scaler.transform(X_test_features)
    
    predictions_proba = model.predict_proba(X_test_scaled)
    predictions_buy_proba = pd.Series(predictions_proba[:, 1], index=X_test_features.index)
    
    logger.debug(f"Iniciando backtest realista com {len(X_test_full)} velas.")

    for date, row in X_test_full.iterrows():
        price = row['close']
        current_portfolio_value = capital + (btc_amount * price)

        if in_position:
            # Lógica de venda com base nos thresholds
            profit_loss_pct = (price / buy_price) - 1
            if profit_loss_pct >= strategy_params['profit_threshold'] or \
               profit_loss_pct <= -strategy_params['stop_loss_threshold']:
                
                # --- Simulação de Custos de Venda ---
                sell_price_with_slippage = price * (1 - SLIPPAGE_RATE)
                capital_after_sell = (btc_amount * sell_price_with_slippage)
                capital = capital_after_sell * (1 - FEE_RATE)
                # ------------------------------------

                btc_amount, in_position, trade_count = 0.0, False, trade_count + 1
        
        # Lógica de compra
        elif predictions_buy_proba.get(date, 0) > strategy_params['prediction_confidence']:
            if capital > 10: # Garante capital mínimo para um trade
                # --- Simulação de Custos de Compra ---
                buy_price_with_slippage = price * (1 + SLIPPAGE_RATE)
                amount_to_buy_btc = (capital / buy_price_with_slippage)
                btc_amount = amount_to_buy_btc * (1 - FEE_RATE)
                # -------------------------------------
                
                capital, buy_price, in_position, trade_count = 0.0, buy_price_with_slippage, True, trade_count + 1
        
        portfolio_values.append(current_portfolio_value)

    # Se a posição ainda estiver aberta no final, liquida pelo último preço (com custos)
    if in_position:
        last_price = X_test_full['close'].iloc[-1]
        capital += (btc_amount * last_price) * (1 - FEE_RATE)
    
    # Cálculo do Sharpe Ratio
    portfolio_returns = pd.Series(portfolio_values).pct_change().dropna()
    if portfolio_returns.std() == 0 or len(portfolio_returns) < 2:
        sharpe_ratio = 0.0
    else:
        # Fator de anualização para dados de 1 minuto
        annualization_factor = np.sqrt(365 * 24 * 60)
        sharpe_ratio = (portfolio_returns.mean() / portfolio_returns.std()) * annualization_factor
        
    logger.debug(f"Backtest concluído. Capital Final: {capital:.2f}, Sharpe: {sharpe_ratio:.2f}, Trades: {trade_count}")
    return capital, sharpe_ratio