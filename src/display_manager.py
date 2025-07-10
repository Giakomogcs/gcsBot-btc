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

# Função de barra de progresso para a otimização (sem alterações)
def get_progress_bar(progress, total, length=40):
    if total == 0: percent = 0
    else: percent = length * (progress / total)
    filled = int(percent)
    bar = '█' * filled + '-' * (length - filled)
    return f"|{bar}| {progress}/{total}"

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


def display_trading_dashboard(status_data: dict):
    """Exibe o painel de controle para o modo de trading a partir de um dicionário de status."""
    if not sys.stdout.isatty():
        return # Não tenta limpar a tela se não for um terminal interativo
    
    clear_screen()
    title = "🤖 GCS-BOT EM OPERAÇÃO 🤖"
    print(f"{'='*70}\n{title:^70}\n{'='*70}")

    # --- Seção 1: Portfólio ---
    portfolio = status_data.get('portfolio', {})
    current_price = portfolio.get('current_price', 0)
    total_value = portfolio.get('total_value_usdt', 0)
    growth_pct = portfolio.get('session_growth_pct', 0)
    pnl_color = "🟢" if growth_pct >= 0 else "🔴"
    growth_display = f"{pnl_color} {growth_pct:+.2%}"

    portfolio_data = [
        ["Capital de Trading (USDT)", f"💵 ${portfolio.get('trading_capital_usdt', 0):,.2f}"],
        ["Posição Aberta (BTC)", f"📈 {portfolio.get('trading_btc_balance', 0):.8f} BTC"],
        ["  └─ Valor Posição (USDT)", f"   ${portfolio.get('trading_btc_value_usdt', 0):,.2f}"],
        ["Tesouraria Longo Prazo (BTC)", f"🏦 {portfolio.get('long_term_btc_holdings', 0):.8f} BTC"],
        ["  └─ Valor Tesouraria (USDT)", f"   ${portfolio.get('long_term_value_usdt', 0):,.2f}"],
        ["Valor Total (USDT)", f"💎 ${total_value:,.2f}"],
    ]
    
    # --- Seção 2: Performance da Sessão ---
    session_stats = status_data.get('session_stats', {})
    trades = session_stats.get('trades', 0)
    wins = session_stats.get('wins', 0)
    losses = trades - wins
    total_pnl = session_stats.get('total_pnl_usdt', 0.0)
    win_rate = (wins / trades * 100) if trades > 0 else 0
    pnl_color_realized = "🟢" if total_pnl >= 0 else "🔴"

    stats_data = [
        ["Trades na Sessão", f"{trades} ({wins}V / {losses}D)"],
        ["Taxa de Acerto", f"{win_rate:.2f}%"],
        ["P&L Realizado (USDT)", f"{pnl_color_realized} ${total_pnl:,.2f}"],
        ["Crescimento na Sessão", growth_display],
    ]
    
    # --- Seção 3: Status do Cérebro do Bot ---
    bot_status = status_data.get('bot_status', {})
    active_specialist = bot_status.get('active_specialist', 'N/A')
    confidence_threshold = bot_status.get('confidence_threshold', 0)
    
    status_info = [
        ["Regime de Mercado Atual", bot_status.get('market_regime', 'N/A')],
        ["Especialista Ativo", active_specialist],
        ["Confiança Mínima (Alvo)", f"{confidence_threshold:.2%}"],
        ["Último Evento", bot_status.get('last_event_message', '')[:65]],
    ]
    
    # --- Seção 4: Último Especialista que Operou ---
    last_op = status_data.get('last_operation', {})
    op_color = "🟢" if last_op.get('pnl_pct', 0) >= 0 else "🔴"
    
    last_op_data = [
        ["Especialista", last_op.get('specialist_name', 'N/A')],
        ["Resultado do Último Trade", f"{op_color} {last_op.get('pnl_pct', 0):+.2%}"],
        ["Trades / Vitórias", f"{last_op.get('total_trades', 0)} / {last_op.get('wins', 0)}"],
        ["P&L Total do Especialista", f"${last_op.get('total_pnl', 0):,.2f}"],
    ]

    print("\n--- 📊 PORTFÓLIO ---"); print(tabulate(portfolio_data, tablefmt="heavy_grid", numalign="right"))
    print("\n--- 📈 PERFORMANCE DA SESSÃO ---"); print(tabulate(stats_data, tablefmt="heavy_grid"))
    print("\n--- 🧠 STATUS DO BOT ---"); print(tabulate(status_info, tablefmt="heavy_grid"))
    print("\n--- 🎯 ÚLTIMA OPERAÇÃO ---"); print(tabulate(last_op_data, tablefmt="heavy_grid"))

    print(f"\n{'='*70}")
    print(f"Preço Atual BTC: ${current_price:,.2f} | Última atualização: {datetime.now().strftime('%H:%M:%S')}")
    sys.stdout.flush()