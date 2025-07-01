import yfinance as yf
import pandas as pd

# Lista de tickers propostos, usando os mais estáveis
tickers_para_testar = {
    'DXY_ETF': 'UUP',
    'VIX_INDEX': '^VIX',
    'GOLD_ETF': 'GLD',
    'US10Y_YIELD': '^TNX'
}

print("Iniciando o teste de download dos tickers...\n")

for nome, ticker in tickers_para_testar.items():
    try:
        print(f"--- Tentando baixar dados para: {nome} ({ticker}) ---")
        
        # Baixa os dados do último ano
        dados = yf.download(ticker, period="1y", interval="1d")
        
        if dados.empty:
            print(f"FALHA: Nenhum dado foi retornado para {ticker}.\n")
        else:
            print(f"SUCESSO: Dados para {ticker} baixados com sucesso!")
            print("Últimos 5 registros:")
            print(dados.tail())
            print("\n" + "="*40 + "\n")
            
    except Exception as e:
        print(f"ERRO CRÍTICO ao baixar {ticker}: {e}\n")