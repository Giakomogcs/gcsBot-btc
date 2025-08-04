# scripts/analyze_backtest.py

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import sys
import os

# Adiciona o diretório raiz ao path para que possamos importar os módulos do projeto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logger import logger
from src.config_manager import settings
from src.database.database_manager import DatabaseManager

def analyze_results():
    """
    Função principal para analisar os resultados do backtest armazenados no InfluxDB.
    """
    logger.info("--- INICIANDO PAINEL DE ANÁLISE DE PERFORMANCE DE PORTFÓLIO ---")

    # --- 1. CONEXÃO E EXTRAÇÃO DE DADOS ---
    logger.info("Conectando ao InfluxDB para buscar os resultados dos trades...")
    try:
        db_manager = DatabaseManager(
            url=settings.database.url,
            token=settings.database.token,
            org=settings.database.org,
            bucket=settings.database.bucket
        )
    except ConnectionError as e:
        logger.error(f"Não foi possível conectar ao banco de dados. Encerrando. Erro: {e}")
        return

    # Usamos a nova função para buscar apenas os trades fechados
    closed_trades_data = db_manager.get_all_closed_trades()
    db_manager.close()

    if not closed_trades_data:
        logger.warning("Nenhum trade fechado encontrado para análise. O backtest pode não ter completado nenhuma transação.")
        return

    # --- 2. TRANSFORMAÇÃO DOS DADOS COM PANDAS ---
    logger.info(f"Encontrados {len(closed_trades_data)} trades fechados. Processando dados...")
    df = pd.DataFrame(closed_trades_data)

    # Convertendo colunas para os tipos corretos para cálculo
    df['_time'] = pd.to_datetime(df['_time'])
    df = df.sort_values(by='_time').reset_index(drop=True)
    numeric_cols = ['pnl_usd', 'entry_price', 'exit_price', 'quantity']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # --- 3. CÁLCULO DAS MÉTRICAS DE PERFORMANCE ---
    initial_capital = settings.backtest.initial_capital
    total_pnl = df['pnl_usd'].sum()
    final_capital = initial_capital + total_pnl
    total_return_pct = (final_capital / initial_capital - 1) * 100

    gross_profit = df[df['pnl_usd'] > 0]['pnl_usd'].sum()
    gross_loss = abs(df[df['pnl_usd'] < 0]['pnl_usd'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    num_trades = len(df)
    winning_trades = len(df[df['pnl_usd'] > 0])
    losing_trades = len(df[df['pnl_usd'] < 0])
    win_rate = (winning_trades / num_trades) * 100 if num_trades > 0 else 0

    # Curva de Capital e Drawdown
    df['cumulative_pnl'] = df['pnl_usd'].cumsum()
    df['equity_curve'] = initial_capital + df['cumulative_pnl']
    df['running_max'] = df['equity_curve'].cummax()
    df['drawdown'] = df['equity_curve'] - df['running_max']
    max_drawdown = df['drawdown'].min()
    max_drawdown_pct = (max_drawdown / df['running_max'].max()) * 100 if df['running_max'].max() > 0 else 0
    
    # Sharpe Ratio (simplificado, anualizado baseado em dias)
    df['daily_return'] = df['pnl_usd'] / df['equity_curve'].shift(1).fillna(initial_capital)
    if not df['daily_return'].empty and df['daily_return'].std() > 0:
        sharpe_ratio = (df['daily_return'].mean() / df['daily_return'].std()) * np.sqrt(365) # Anualizando
    else:
        sharpe_ratio = 0.0

    # --- 4. EXIBIÇÃO DO RELATÓRIO FINANCEIRO ---
    print("\n" + "="*80)
    print(" " * 25 + "RELATÓRIO DE PERFORMANCE FINANCEIRA")
    print("="*80)
    print(f"\nPeríodo do Backtest: {df['_time'].min().date()} a {df['_time'].max().date()}")
    print("-" * 40)
    print("Resultados Gerais:")
    print(f"  - Capital Inicial:       ${initial_capital:,.2f}")
    print(f"  - Capital Final:         ${final_capital:,.2f}")
    print(f"  - Lucro/Prejuízo Total:  ${total_pnl:,.2f}")
    print(f"  - Retorno Total:         {total_return_pct:.2f}%")
    print("-" * 40)
    print("Métricas de Risco e Eficiência:")
    print(f"  - Fator de Lucro:        {profit_factor:.2f}")
    print(f"  - Sharpe Ratio (Anual.): {sharpe_ratio:.2f}")
    print(f"  - Máximo Drawdown:       ${max_drawdown:,.2f} ({max_drawdown_pct:.2f}%)")
    print("-" * 40)
    print("Estatísticas de Trades:")
    print(f"  - Total de Trades:       {num_trades}")
    print(f"  - Trades Vencedores:     {winning_trades}")
    print(f"  - Trades Perdedores:     {losing_trades}")
    print(f"  - Taxa de Acerto:        {win_rate:.2f}%")
    print("\n" + "="*80)

    # --- 5. GERAÇÃO DO GRÁFICO DA CURVA DE CAPITAL ---
    logger.info("Gerando gráfico da curva de capital...")
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(df['_time'], df['equity_curve'], label='Curva de Capital', color='royalblue', linewidth=2)
    
    # Formatação
    ax.set_title('Curva de Capital ao Longo do Tempo', fontsize=16)
    ax.set_xlabel('Data', fontsize=12)
    ax.set_ylabel('Capital ($)', fontsize=12)
    formatter = mticker.FuncFormatter(lambda x, p: f'${x:,.0f}')
    ax.yaxis.set_major_formatter(formatter)
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()
    
    # Salvar o gráfico em um arquivo
    output_filename = "equity_curve.png"
    plt.savefig(output_filename)
    logger.info(f"✅ Gráfico salvo como '{output_filename}'")
    
    # Exibir o gráfico
    plt.show()


if __name__ == "__main__":
    analyze_results()