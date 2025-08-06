# src/display_manager.py

import os
import sys
import time
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich.progress_bar import ProgressBar
from rich.box import HEAVY

console = Console()

def display_trading_dashboard(status_data: dict):
    """Exibe o painel de controle para o modo de trading a partir de um dicionário de status."""
    if not sys.stdout.isatty():
        return

    os.system('cls' if os.name == 'nt' else 'clear')
    layout = Layout()

    layout.split(
        Layout(name="header", size=3),
        Layout(ratio=1, name="main"),
        Layout(size=10, name="footer"),
    )

    layout["main"].split_row(Layout(name="left", ratio=1), Layout(name="right", ratio=2))
    layout["left"].split_column(
        Layout(name="portfolio"),
        Layout(name="session_stats"),
    )

    header = Panel(Text("🤖 GCS-BOT EM OPERAÇÃO 🤖", justify="center", style="bold white on blue"))
    layout["header"].update(header)

    # Painel do Portfólio
    portfolio = status_data.get('portfolio', {})
    portfolio_table = Table(title="📊 PORTFÓLIO ATUAL")
    portfolio_table.add_column("Ativo", style="cyan")
    portfolio_table.add_column("Quantidade", style="magenta", justify="right")
    portfolio_table.add_column("Valor (USDT)", style="green", justify="right")

    portfolio_table.add_row("Saldo BTC", f"{portfolio.get('btc_balance', 0):.8f}", f"${portfolio.get('btc_value_usdt', 0):,.2f}")
    portfolio_table.add_row("Saldo USDT", f"{portfolio.get('usd_balance', 0):,.2f}", f"${portfolio.get('usd_balance', 0):,.2f}")
    portfolio_table.add_row(Text("Total", style="bold"), "", Text(f"${portfolio.get('total_value_usdt', 0):,.2f}", style="bold green"))
    layout["portfolio"].update(Panel(portfolio_table))

    # Painel de Estatísticas da Sessão
    session_stats = status_data.get('session_stats', {})
    stats_table = Table(title="📈 ESTATÍSTICAS DA SESSÃO")
    stats_table.add_column("Métrica", style="cyan")
    stats_table.add_column("Valor", style="magenta", justify="right")

    pnl = session_stats.get('total_pnl_usdt', 0.0)
    pnl_color = "green" if pnl >= 0 else "red"
    stats_table.add_row("P&L Total Realizado", Text(f"${pnl:,.2f}", style=pnl_color))
    stats_table.add_row("Posições Abertas", str(session_stats.get('open_positions_count', 0)))
    stats_table.add_row("Trades Fechados", str(session_stats.get('closed_trades_count', 0)))
    layout["session_stats"].update(Panel(stats_table))

    # Painel de Resumo de Trades (agora no lado direito)
    trade_summary = status_data.get('trade_summary', [])
    summary_table = Table(title="📜 RESUMO DOS ÚLTIMOS TRADES")
    summary_table.add_column("ID", style="dim")
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Preço Entrada", style="cyan", justify="right")
    summary_table.add_column("Quantidade", style="magenta", justify="right")
    summary_table.add_column("Data", style="yellow")

    for trade in trade_summary:
        status_style = "green" if trade['status'] == 'OPEN' else ("yellow" if "PARTIAL" in trade.get('exit_reason', '') else "dim")
        summary_table.add_row(
            trade['trade_id'][:8],
            Text(trade['status'], style=status_style),
            f"${trade.get('entry_price', 0):,.2f}",
            f"{trade.get('quantity_btc', 0):.6f} BTC",
            datetime.fromisoformat(trade['timestamp']).strftime('%Y-%m-%d %H:%M')
        )
    layout["right"].update(Panel(summary_table))

    # Footer com status do bot
    bot_status = status_data.get('bot_status', {})
    current_price = portfolio.get('current_price', 0)
    last_update_str = bot_status.get('last_update', '')
    last_update_dt = datetime.fromisoformat(last_update_str) if last_update_str else datetime.now()

    footer_text = Text(f"Preço Atual {bot_status.get('symbol', 'BTC/USDT')}: ${current_price:,.2f} | Última Atualização: {last_update_dt.strftime('%H:%M:%S')}", justify="center")
    layout["footer"].update(Panel(footer_text))
    
    console.print(layout)

def display_optimization_dashboard(status_data: dict):
    """Exibe o painel de controle para o modo de otimização a partir de um dicionário de status."""
    os.system('cls' if os.name == 'nt' else 'clear') # Limpa a tela
    
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(ratio=1, name="main"),
        Layout(size=3, name="footer"),
    )

    layout["main"].split_row(Layout(name="left", ratio=2), Layout(name="right", ratio=3))
    layout["left"].split_column(
        Layout(name="progress", size=7),
        Layout(name="summary"),
    )
    layout["right"].split_column(
        Layout(name="best_trial"),
        Layout(name="pruning_stats"),
    )
    
    # --- Header ---
    header_text = Text("🤖 GCS-BOT OPTIMIZER 🤖", justify="center", style="bold white on blue")
    layout["header"].update(Panel(header_text, box=HEAVY))

    # --- (Left) Progress Panel ---
    situation = status_data.get("situation_atual", "Aguardando...")
    n_trials = status_data.get("n_trials", 0)
    total_trials = status_data.get("total_trials", 1) # Evita divisão por zero
    progress_pct = (n_trials / total_trials) * 100
    
    progress_table = Table.grid(expand=True)
    progress_table.add_column(style="cyan")
    progress_table.add_column(style="magenta")
    progress_table.add_row("Otimizando Situação:", f"[bold]{situation}[/bold]")
    progress_table.add_row("Trials Executados:", f"{n_trials} de {total_trials}")
    progress_table.add_row("Progresso:", ProgressBar(total=100, completed=progress_pct, complete_style="green"))
    layout["progress"].update(Panel(progress_table, title="[bold]Progresso Atual[/bold]", border_style="green"))

    # --- (Left) Summary Panel ---
    summary_table = Table(title="[bold]Resumo Geral[/bold]", box=None, show_header=False)
    summary_table.add_column(style="cyan", no_wrap=True)
    summary_table.add_column(style="magenta")
    start_time = status_data.get("start_time", time.time())
    elapsed = timedelta(seconds=int(time.time() - start_time))
    summary_table.add_row("Tempo Decorrido:", str(elapsed))
    summary_table.add_row("Trials Concluídos:", str(status_data.get("n_complete", 0)))
    summary_table.add_row("Trials em Execução:", str(status_data.get("n_running", 0)))
    summary_table.add_row("Trials Podados (Pruned):", str(status_data.get("n_pruned", 0)))
    layout["summary"].update(Panel(summary_table, border_style="cyan"))
    
    # --- (Right) Best Trial Panel ---
    best_trial_data = status_data.get("best_trial_data")
    if best_trial_data:
        best_score = best_trial_data.get("value", 0.0)
        best_params = best_trial_data.get("params", {})
        user_attrs = best_trial_data.get("user_attrs", {})

        best_trial_table = Table(title=f"🏆 Melhor Trial (Score: [bold green]{best_score:.4f}[/bold green])", box=HEAVY, show_header=False)
        best_trial_table.add_column(style="cyan")
        best_trial_table.add_column(style="yellow")
        best_trial_table.add_row("[bold]-- Métricas --[/bold]", "")
        best_trial_table.add_row("Trades Totais:", str(user_attrs.get("total_trades", "N/A")))
        best_trial_table.add_row("Sortino Mediano:", f"{user_attrs.get('median_sortino', 0.0):.3f}")
        best_trial_table.add_row("Profit Factor Mediano:", f"{user_attrs.get('median_profit_factor', 0.0):.3f}")
        best_trial_table.add_row("\n[bold]-- Parâmetros --[/bold]", "")
        
        # Exibe os 5 parâmetros mais importantes
        params_to_show = {k: v for k, v in best_params.items() if isinstance(v, (int, float))}
        sorted_params = sorted(params_to_show.items(), key=lambda item: abs(item[1]), reverse=True)[:5]

        for param, value in sorted_params:
            if isinstance(value, float): value = f"{value:.4f}"
            best_trial_table.add_row(f"{param}:", str(value))
        
        layout["right"].update(Panel(best_trial_table, border_style="yellow"))
    else:
        layout["right"].update(Panel(Text("Aguardando o primeiro trial ser concluído...", justify="center"), title="🏆 Melhor Trial", border_style="yellow"))

    # --- (Right) Pruning Stats ---
    pruning_summary = status_data.get("pruning_reason_summary", {})
    if pruning_summary:
        pruning_table = Table(title="[bold]Motivos de Pruning (Poda)[/bold]", box=None, show_header=False)
        pruning_table.add_column(style="cyan")
        pruning_table.add_column(style="magenta")
        for reason, count in sorted(pruning_summary.items(), key=lambda item: item[1], reverse=True):
            pruning_table.add_row(reason, str(count))
        layout["pruning_stats"].update(Panel(pruning_table, border_style="red"))
        
    # --- Footer ---
    footer_text = Text(f"Última atualização: {datetime.now().strftime('%H:%M:%S')} | Pressione CTRL+C para sair", justify="center")
    layout["footer"].update(Panel(footer_text, box=HEAVY))

    console.print(layout)