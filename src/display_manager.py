# src/display_manager.py (VERSÃO 2.0 - Desacoplado do Optuna)

import os
import sys
from datetime import datetime
import pandas as pd
from tabulate import tabulate
import time

def clear_screen():
    """Limpa a tela do terminal."""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_progress_bar(progress, total, length=40):
    if total == 0:
        percent = 0
    else:
        percent = length * (progress / total)
    filled = int(percent)
    bar = '█' * filled + '-' * (length - filled)
    return f"|{bar}| {progress}/{total}"

# <<< ALTERADO >>> A função agora recebe um dicionário 'status_data'
def display_optimization_dashboard(status_data: dict):
    """Exibe o painel de controle para o modo de otimização a partir de um dicionário de status."""
    clear_screen()
    title = "🚀 OTIMIZANDO ESTRATÉGIAS DE TRADING 🚀"
    print(f"{'='*60}\n{title:^60}\n{'='*60}")
    
    # Extrai os dados do dicionário
    regime_atual = status_data.get('regime_atual', 'N/A')
    n_trials = status_data.get('n_trials', 0)
    total_trials = status_data.get('total_trials', 0)
    start_time = status_data.get('start_time', time.time())
    n_complete = status_data.get('n_complete', 0)
    n_pruned = status_data.get('n_pruned', 0)
    n_running = status_data.get('n_running', 0)
    
    elapsed_time = time.time() - start_time
    progress_bar = get_progress_bar(n_trials, total_trials)
    
    print(f"\nRegime Atual: [ {regime_atual.upper()} ]")
    print(f"Progresso:    {progress_bar}")
    print(f"Status:       Completos: {n_complete}, Podados: {n_pruned}, Em Execução: {n_running}")
    print(f"Tempo Decorrido: {time.strftime('%H:%M:%S', time.gmtime(elapsed_time))}")

    print("\n--- 🏆 Melhores Resultados Até Agora ---")
    
    best_value = status_data.get('best_value')
    best_params = status_data.get('best_params')

    if best_value is not None and best_params is not None:
        print(f"Melhor Score: {best_value:.4f}")
        
        # Para evitar tabelas muito grandes
        if len(best_params) > 10:
             params_to_show = dict(list(best_params.items())[:10])
             params_to_show['...'] = '...'
        else:
            params_to_show = best_params

        params_df = pd.DataFrame(list(params_to_show.items()), columns=['Parâmetro', 'Valor'])
        print(tabulate(params_df, headers="keys", tablefmt="heavy_grid", showindex=False))
    else:
        print("Ainda aguardando o primeiro trial ser concluído com sucesso...")
        
    print(f"\nÚltima atualização: {datetime.now().strftime('%H:%M:%S')}")
    sys.stdout.flush()


def display_trading_dashboard(portfolio, trade_stats, regime, last_event=""):
    """Exibe o painel de controle para o modo de trading, se em terminal interativo."""
    if not sys.stdout.isatty():
        return
    
    clear_screen()
    title = "🤖 GCS-BOT EM OPERAÇÃO 🤖"
    print(f"{'='*60}\n{title:^60}\n{'='*60}")
    
    current_price = portfolio.get_current_price() or 0
    total_value = portfolio.get_total_portfolio_value_usdt(current_price)
    growth_pct = (total_value / portfolio.initial_total_value_usdt - 1) * 100 if portfolio.initial_total_value_usdt > 0 else 0
    pnl_color = "🟢" if growth_pct >= 0 else "🔴"
    growth_display = f"{pnl_color} {growth_pct:+.2f}%"

    portfolio_data = [
        ["Capital de Trading (USDT)", f"💵 ${portfolio.trading_capital_usdt:,.2f}"],
        ["Tesouraria (BTC)", f"🏦 {portfolio.long_term_btc_holdings:.8f}"],
        ["  └─ Valor (USDT)", f"   ${(portfolio.long_term_btc_holdings * current_price):,.2f}"],
        ["Valor Total (USDT)", f"💎 ${total_value:,.2f}"],
    ]

    trades = trade_stats.get('trades', 0)
    wins = trade_stats.get('wins', 0)
    total_pnl = trade_stats.get('total_pnl', 0.0)
    win_rate = (wins / trades * 100) if trades > 0 else 0
    pnl_color_realized = "🟢" if total_pnl >= 0 else "🔴"

    stats_data = [
        ["Trades na Sessão", f"{trades} ({wins}V / {trades-wins}D)"],
        ["Taxa de Acerto", f"{win_rate:.2f}%"],
        ["P&L Realizado", f"{pnl_color_realized} ${total_pnl:,.2f}"],
    ]

    bot_status = [
        ["Regime de Mercado", regime],
        ["Crescimento da Sessão", growth_display],
        ["Último Evento", last_event[:55]],
    ]
    
    print("\n--- 📊 PORTFÓLIO ---"); print(tabulate(portfolio_data, tablefmt="plain"))
    print("\n--- 📈 ESTATÍSTICAS ---"); print(tabulate(stats_data, tablefmt="plain"))
    print("\n--- ℹ️ STATUS ---"); print(tabulate(bot_status, tablefmt="plain"))
    print(f"\n{'='*60}")
    print(f"Preço Atual BTC: ${current_price:,.2f} | Última atualização: {datetime.now().strftime('%H:%M:%S')}")
    sys.stdout.flush()