import os
import datetime
import pandas as pd
from binance.client import Client
import yfinance as yf
import time

# --- CONFIGURAÇÕES ---
DATA_DIR = "data"
START_DATE_STR = "2018-01-01"
SYMBOL = "BTCUSDT"
INTERVAL = Client.KLINE_INTERVAL_1MINUTE

# Tickers macroeconômicos usados no seu data_manager.py
MACRO_TICKERS = {
    'DXY': 'DX-Y.NYB',  # Índice do Dólar
    'VIX': '^VIX',      # Índice de Volatilidade (Medo)
    'GOLD': 'GC=F',     # Ouro
    'TNX': '^TNX'       # Juros de 10 anos EUA
}

# --- FUNÇÕES DE DOWNLOAD ---

def download_btc_data(symbol, interval, start_str, data_dir):
    """Baixa os dados do BTC em lotes para não sobrecarregar a API."""
    client = Client()
    output_file = os.path.join(data_dir, f"full_historical_{symbol}.csv")
    
    print(f"--- Iniciando download massivo para {symbol} ---")
    print(f"Dados serão salvos em: {output_file}")

    start_ts = int(datetime.datetime.strptime(start_str, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.datetime.now().timestamp() * 1000)
    
    all_klines = []
    while start_ts < end_ts:
        try:
            # Baixa em lotes de 1000 velas (limite da API)
            klines = client.get_historical_klines(symbol, interval, start_ts)
            if not klines:
                break # Sai do loop se não houver mais dados
            
            all_klines.extend(klines)
            last_timestamp = klines[-1][0]
            
            # Converte timestamps para datas legíveis para o log
            start_date_log = pd.to_datetime(start_ts, unit='ms')
            last_date_log = pd.to_datetime(last_timestamp, unit='ms')
            
            print(f"  ... Lote baixado: de {start_date_log.strftime('%Y-%m-%d')} até {last_date_log.strftime('%Y-%m-%d')}. Total de velas: {len(all_klines)}")
            
            start_ts = last_timestamp + 1 # Próximo lote começa após a última vela
            time.sleep(0.5) # Pausa para não sobrecarregar a API

        except Exception as e:
            print(f"ERRO durante o download do BTC: {e}. Tentando novamente em 5 segundos...")
            time.sleep(5)
            
    print("\nDownload do BTC concluído. Processando e salvando...")
    df = pd.DataFrame(all_klines, columns=['timestamp','open','high','low','close','volume','close_time','qav','nt','tbbav','tbqav','ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # Seleciona e converte colunas para o formato correto
    df = df[['open','high','low','close','volume']].astype(float)
    df.to_csv(output_file)
    print(f"✅ SUCESSO! Dados do BTC salvos. Total de {len(df)} registros.")


def download_macro_data(tickers, start_str, data_dir):
    """Baixa dados diários para todos os tickers macroeconômicos."""
    print("\n--- Iniciando download dos dados macroeconômicos ---")
    start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d")

    for name, ticker in tickers.items():
        output_file = os.path.join(data_dir, f"MACRO_{ticker}.csv")
        try:
            print(f"  Baixando dados para {name} ({ticker})...")
            dados = yf.download(ticker, start=start_date, interval="1d")
            if dados.empty:
                print(f"  AVISO: Nenhum dado foi retornado para {ticker}.")
            else:
                dados.to_csv(output_file)
                print(f"  ✅ SUCESSO! Dados para {name} salvos em {output_file}")
        except Exception as e:
            print(f"  ERRO CRÍTICO ao baixar {ticker}: {e}")
        time.sleep(1) # Pausa entre as chamadas do yfinance


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # 1. Baixar dados do Bitcoin
    download_btc_data(SYMBOL, INTERVAL, START_DATE_STR, DATA_DIR)
    
    # 2. Baixar dados macroeconômicos
    download_macro_data(MACRO_TICKERS, START_DATE_STR, DATA_DIR)
    
    print("\n--- PROCESSO DE DOWNLOAD CONCLUÍDO ---")
    print("Todos os arquivos necessários estão na pasta 'data'.")