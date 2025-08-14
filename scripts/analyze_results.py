import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import sys
import argparse

# Adiciona o diretório raiz do projeto ao sys.path
# para permitir a importação de módulos do jules_bot.
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager

def analyze_confidence_performance(environment: str):
    """
    Carrega os resultados do backtest do banco de dados para analisar
    a correlação entre a confiança do modelo e a performance dos trades.
    """
    print(f"--- Iniciando Análise de Confiança vs. Performance do ambiente '{environment}' ---")

    # Instancia o DatabaseManager com o modo de execução correto
    db_config = config_manager.get_section('INFLUXDB')
    if environment == 'test':
        db_config['bucket'] = 'jules_bot_test_v1'
    elif environment == 'backtest':
        db_config['bucket'] = 'jules_bot_backtest_v1'
    db_manager = DatabaseManager(config=db_config)


    # Carrega os dados diretamente do banco de dados
    analysis_df = db_manager.get_all_trades_for_analysis()

    # Verifica se foram encontrados trades
    if analysis_df.empty:
        print("\nAVISO: Nenhum trade encontrado no banco de dados para o período especificado.")
        print("Por favor, execute o backtest primeiro para gerar dados.")
        return

    print(f"Carregados {len(analysis_df)} trades do banco de dados.")

    # Remove trades onde a confiança não foi registrada (se houver)
    if analysis_df['final_confidence'].isnull().any():
        print("AVISO: Alguns trades não tinham um valor de 'final_confidence' registrado.")
        analysis_df.dropna(subset=['final_confidence'], inplace=True)

    # Cria uma coluna para identificar se o trade foi vencedor (Win) ou não
    analysis_df['is_win'] = analysis_df['pnl'] > 0

    # Cria "baldes" (bins) de confiança para agrupar os resultados
    confidence_bins = np.arange(0.6, 1.01, 0.05)
    analysis_df['confidence_bin'] = pd.cut(analysis_df['final_confidence'], bins=confidence_bins, right=False)

    # Agrupa por bin de confiança e calcula as métricas
    results = analysis_df.groupby('confidence_bin').agg(
        total_trades=('is_win', 'count'),
        winning_trades=('is_win', 'sum'),
        total_pnl=('pnl', 'sum')
    ).reset_index()

    results['win_rate'] = (results['winning_trades'] / results['total_trades']) * 100
    
    # Limpa o nome do bin para exibição
    results['confidence_bin'] = results['confidence_bin'].astype(str)

    print("\n--- Performance por Faixa de Confiança ---")
    print(results[['confidence_bin', 'total_trades', 'win_rate', 'total_pnl']].round(2))
    print("------------------------------------------")

    # --- Visualização ---
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax1 = plt.subplots(figsize=(14, 7))

    # Gráfico de barras para o número de trades
    sns.barplot(x='confidence_bin', y='total_trades', data=results, ax=ax1, alpha=0.6, color='b', label='Número de Trades')
    ax1.set_xlabel('Faixa de Confiança', fontsize=12)
    ax1.set_ylabel('Número de Trades', fontsize=12, color='b')
    ax1.tick_params(axis='y', labelcolor='b')
    plt.xticks(rotation=45)

    # Gráfico de linha para a taxa de acerto
    ax2 = ax1.twinx()
    sns.lineplot(x='confidence_bin', y='win_rate', data=results, ax=ax2, color='r', marker='o', label='Taxa de Acerto (%)')
    ax2.set_ylabel('Taxa de Acerto (%)', fontsize=12, color='r')
    ax2.tick_params(axis='y', labelcolor='r')
    ax2.set_ylim(0, max(50, results['win_rate'].max() * 1.1)) # Garante um bom limite no eixo Y

    plt.title('Taxa de Acerto e Volume de Trades por Nível de Confiança', fontsize=16)
    fig.tight_layout()
    
    # Salva o gráfico
    output_path = 'data/output'
    os.makedirs(output_path, exist_ok=True)
    plot_filepath = os.path.join(output_path, 'confidence_vs_performance.png')
    plt.savefig(plot_filepath)
    
    print(f"\nGráfico de análise salvo em: {plot_filepath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analisa a performance dos trades em relação à confiança do modelo."
    )
    parser.add_argument(
        '--env',
        type=str,
        default='trade',
        choices=['trade', 'test', 'backtest'],
        help='O ambiente de execução para analisar (default: trade)'
    )
    args = parser.parse_args()

    analyze_confidence_performance(environment=args.env)