# src/display_manager.py

import os
import sys
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich.text import Text

console = Console()

def display_trading_dashboard(status_data: dict):
    """Exibe o painel de controle para o modo de trading a partir de um dicionário de status."""
    if not sys.stdout.isatty():
        return

    layout = Layout()

    layout.split(
        Layout(name="header", size=3),
        Layout(ratio=1, name="main"),
        Layout(size=3, name="footer"),
    )

    layout["main"].split_row(Layout(name="left"), Layout(name="right"))
    layout["left"].split_column(
        Layout(name="portfolio"),
        Layout(name="session_stats"),
    )
    layout["right"].split_column(
        Layout(name="bot_status"),
        Layout(name="last_operation"),
    )

    header = Panel(Text("🤖 GCS-BOT EM OPERAÇÃO 🤖", justify="center", style="bold white on blue"))
    layout["header"].update(header)

    portfolio = status_data.get('portfolio', {})
    portfolio_table = Table(title="📊 PORTFÓLIO")
    portfolio_table.add_column("Ativo", style="cyan")
    portfolio_table.add_column("Valor", style="magenta")
    portfolio_table.add_row("Capital de Trading (USDT)", f"💵 ${portfolio.get('trading_capital_usdt', 0):,.2f}")
    portfolio_table.add_row("Posição Aberta (BTC)", f"📈 {portfolio.get('trading_btc_balance', 0):.8f} BTC")
    portfolio_table.add_row("  └─ Valor Posição (USDT)", f"   ${portfolio.get('trading_btc_value_usdt', 0):,.2f}")
    portfolio_table.add_row("Tesouraria Longo Prazo (BTC)", f"🏦 {portfolio.get('long_term_btc_holdings', 0):.8f} BTC")
    portfolio_table.add_row("  └─ Valor Tesouraria (USDT)", f"   ${portfolio.get('long_term_value_usdt', 0):,.2f}")
    portfolio_table.add_row("Valor Total (USDT)", f"💎 ${portfolio.get('total_value_usdt', 0):,.2f}")
    layout["portfolio"].update(Panel(portfolio_table))

    session_stats = status_data.get('session_stats', {})
    session_stats_table = Table(title="📈 PERFORMANCE DA SESSÃO")
    session_stats_table.add_column("Métrica", style="cyan")
    session_stats_table.add_column("Valor", style="magenta")
    trades = session_stats.get('trades', 0)
    wins = session_stats.get('wins', 0)
    losses = trades - wins
    win_rate = (wins / trades * 100) if trades > 0 else 0
    total_pnl = session_stats.get('total_pnl_usdt', 0.0)
    pnl_color_realized = "green" if total_pnl >= 0 else "red"
    session_stats_table.add_row("Trades na Sessão", f"{trades} ({wins}V / {losses}D)")
    session_stats_table.add_row("Taxa de Acerto", f"{win_rate:.2f}%")
    session_stats_table.add_row("P&L Realizado (USDT)", Text(f"${total_pnl:,.2f}", style=pnl_color_realized))
    growth_pct = portfolio.get('session_growth_pct', 0)
    pnl_color = "green" if growth_pct >= 0 else "red"
    session_stats_table.add_row("Crescimento na Sessão", Text(f"{growth_pct:+.2%}", style=pnl_color))
    layout["session_stats"].update(Panel(session_stats_table))

    bot_status = status_data.get('bot_status', {})
    bot_status_table = Table(title="🧠 STATUS DO BOT")
    bot_status_table.add_column("Parâmetro", style="cyan")
    bot_status_table.add_column("Valor", style="magenta")
    bot_status_table.add_row("Situação de Mercado Atual", str(bot_status.get('market_situation', 'N/A')))
    bot_status_table.add_row("Modelo Ativo", bot_status.get('active_model', 'N/A'))
    bot_status_table.add_row("Confiança Mínima (Alvo)", f"{bot_status.get('confidence_threshold', 0):.2%}")
    bot_status_table.add_row("Último Evento", bot_status.get('last_event_message', '')[:65])
    bot_status_table.add_row("Recomendação", bot_status.get('recommendation', 'N/A'))
    layout["bot_status"].update(Panel(bot_status_table))

    last_op = status_data.get('last_operation', {})
    last_op_table = Table(title="🎯 ÚLTIMA OPERAÇÃO")
    last_op_table.add_column("Métrica", style="cyan")
    last_op_table.add_column("Valor", style="magenta")
    op_color = "green" if last_op.get('pnl_pct', 0) >= 0 else "red"
    last_op_table.add_row("Situação", last_op.get('situation_name', 'N/A'))
    last_op_table.add_row("Resultado do Último Trade", Text(f"{last_op.get('pnl_pct', 0):+.2%}", style=op_color))
    last_op_table.add_row("Trades / Vitórias", f"{last_op.get('total_trades', 0)} / {last_op.get('wins', 0)}")
    last_op_table.add_row("P&L Total da Situação", f"${last_op.get('total_pnl', 0):,.2f}")
    layout["last_operation"].update(Panel(last_op_table))

    footer = Panel(Text(f"Preço Atual BTC: ${portfolio.get('current_price', 0):,.2f} | Última atualização: {datetime.now().strftime('%H:%M:%S')}", justify="center"))
    layout["footer"].update(footer)
    
    with Live(layout, console=console, screen=True, transient=True):
        pass
