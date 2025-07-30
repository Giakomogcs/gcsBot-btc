import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os

def analyze_confidence_performance():
    """
    Carrega os resultados do backtest e o histórico de confiança para analisar
    a correlação entre a confiança do modelo e a performance dos trades.
    """
    print("--- Iniciando Análise de Confiança vs. Performance ---")

    # Caminhos para os arquivos de dados
    trades_file = 'data/output/trades_history.csv'
    confidence_file = 'data/output/confidence_history.csv'

    # Verifica se os arquivos necessários existem
    if not os.path.exists(trades_file) or not os.path.exists(confidence_file):
        print("\nERRO: Arquivos 'trades_history.csv' ou 'confidence_history.csv' não encontrados.")
        print("Por favor, execute o backtest primeiro para gerar esses arquivos.")
        return

    # Carrega os dados
    trades_df = pd.read_csv(trades_file, parse_dates=['entry_time', 'exit_time'])
    confidence_df = pd.read_csv(confidence_file, parse_dates=['timestamp'])
    
    print(f"Carregados {len(trades_df)} trades e {len(confidence_df)} registros de confiança.")

    # Junta os trades com a confiança que o bot tinha no momento da entrada
    # Renomeia a coluna 'timestamp' para 'entry_time' para o merge
    confidence_df.rename(columns={'timestamp': 'entry_time'}, inplace=True)
    
    # O merge junta as informações de confiança a cada trade correspondente
    analysis_df = pd.merge(trades_df, confidence_df, on='entry_time', how='left')

    if analysis_df['final_confidence'].isnull().any():
        print("AVISO: Alguns trades não encontraram um registro de confiança correspondente.")
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
    analyze_confidence_performance()