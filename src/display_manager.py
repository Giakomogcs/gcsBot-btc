# src/display_manager.py (VERSÃO 4.2 - Final e Refinada)

import os
import sys
from datetime import datetime
import pandas as pd
from tabulate import tabulate
import time

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_progress_bar(progress, total, length=40):
    if total == 0:
        percent = 0
    else:
        percent = length * (progress / total)
    filled = int(percent)
    bar = '█' * filled + '-' * (length - filled)
    return f"|{bar}| {progress}/{total}"

def display_optimization_dashboard(status_data: dict):
    """Exibe o painel de controle completo com resumo e análise de poda."""
    clear_screen()
    title = "🏭 FÁBRICA DE ESPECIALISTAS GCS-BOT 🏭"
    print(f"{'='*80}\n{title:^80}\n{'='*80}")

    # --- Seção 1: Resumo dos Especialistas Já Concluídos ---
    completed = status_data.get('completed_specialists', {})
    if completed:
        print("\n--- ✅ ESPECIALISTAS CONCLUÍDOS ---")
        summary_data = []
        headers = ["Especialista", "Status", "Melhor Score", "Modelo Salvo"]
        for name, results in completed.items():
<<<<<<< HEAD
=======
            # Apenas mostra o resultado final de um ciclo de otimização, não os fallbacks
>>>>>>> 95e35a27dc4d04ede3632d6004071bcd0923a05d
            if results.get('status') in ['Optimized and Saved', 'Skipped - Low Score', 'Skipped - All Trials Pruned']:
                summary_data.append([
                    name,
                    results.get('status'),
                    f"{results.get('score', 0):.4f}",
                    results.get('model_file', 'N/A')
                ])
        if summary_data:
            print(tabulate(summary_data, headers=headers, tablefmt="heavy_grid"))
        else:
            print("Nenhum especialista concluiu seu ciclo de otimização ainda...")

    # --- Seção 2: Otimização em Andamento ---
    print("\n--- 🔄 OTIMIZAÇÃO ATUAL ---")
    regime_atual = status_data.get('regime_atual', 'Aguardando...')
    progresso_str = f"Progresso: {get_progress_bar(status_data.get('n_trials', 0), status_data.get('total_trials', 0))}"
    status_str = f"Status: Completos: {status_data.get('n_complete', 0)}, Podados: {status_data.get('n_pruned', 0)}, Em Execução: {status_data.get('n_running', 0)}"
    tempo_str = f"Tempo Decorrido: {time.strftime('%H:%M:%S', time.gmtime(time.time() - status_data.get('start_time', time.time())))}"
    print(f"Especialista: [ {regime_atual.upper()} ]\n{progresso_str}\n{status_str}\n{tempo_str}")

<<<<<<< HEAD
    print("\n--- 📊 PLACAR GERAL DE PODAS (ACUMULADO) ---")
=======
    print("\n--- 📊 PLACAR GERAL DE PODAS (TODOS OS ESPECIALISTAS) ---")
>>>>>>> 95e35a27dc4d04ede3632d6004071bcd0923a05d
    reason_summary = status_data.get('pruning_reason_summary', {})
    if reason_summary:
        summary_data = [[reason, count] for reason, count in reason_summary.items()]
        print(tabulate(summary_data, headers=["Motivo da Poda", "Contagem Total"], tablefmt="heavy_grid"))
    else:
        print("Nenhum trial foi podado ainda.")

    # --- Seção 3: Detalhes do Melhor Resultado Encontrado ---
<<<<<<< HEAD
    print("\n--- 🏆 MELHORES RESULTADOS (ESPECIALISTA ATUAL) ---")
=======
    print("\n--- 🏆 MELHORES RESULTADOS (ATÉ AGORA) ---")
>>>>>>> 95e35a27dc4d04ede3632d6004071bcd0923a05d
    best_trial_data = status_data.get('best_trial_data')
    if best_trial_data:
        user_attrs = best_trial_data.get('user_attrs', {})
        details_data = [
            ["Melhor Score", f"{best_trial_data.get('value', 0.0):.4f}"],
            ["Total de Trades (simulado)", user_attrs.get("total_trades", "N/A")],
            ["Sortino Ratio (mediana)", f"{user_attrs.get('median_sortino', 0):.2f}"],
            ["Profit Factor (mediana)", f"{user_attrs.get('median_profit_factor', 0):.2f}"]
        ]
        print(tabulate(details_data, tablefmt="plain"))
    else:
        print("Aguardando o primeiro trial ser concluído com sucesso...")

    # --- Seção 4: Análise de Trials Podados ---
<<<<<<< HEAD
    print("\n--- 🕵️ ANÁLISE DE PODAS RECENTES (ÚLTIMOS 5) ---")
=======
    print("\n--- 🕵️ ANÁLISE DE TRIALS PODADOS (ÚLTIMOS 5) ---")
>>>>>>> 95e35a27dc4d04ede3632d6004071bcd0923a05d
    pruned_history = status_data.get('pruned_trials_history', [])
    if pruned_history:
        pruned_data = [[item['number'], item['reason']] for item in reversed(pruned_history)]
        print(tabulate(pruned_data, headers=["Trial #", "Motivo da Poda"], tablefmt="heavy_grid"))
    else:
        print("Nenhum trial foi podado ainda nesta sessão.")
        
    print(f"\nÚltima atualização: {datetime.now().strftime('%H:%M:%S')}")
    sys.stdout.flush()

def display_trading_dashboard(status_data: dict):
    """Exibe o painel de controle para o modo de trading a partir de um dicionário de status."""
    if not sys.stdout.isatty():
        return
    
    clear_screen()
    title = "🤖 GCS-BOT EM OPERAÇÃO 🤖"
    print(f"{'='*70}\n{title:^70}\n{'='*70}")

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
    
    bot_status = status_data.get('bot_status', {})
    status_info = [
        ["Regime de Mercado Atual", bot_status.get('market_regime', 'N/A')],
        ["Especialista Ativo", bot_status.get('active_specialist', 'N/A')],
        ["Confiança Mínima (Alvo)", f"{bot_status.get('confidence_threshold', 0):.2%}"],
        ["Último Evento", bot_status.get('last_event_message', '')[:65]],
    ]
    
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