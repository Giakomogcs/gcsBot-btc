# src/core/feature_engineering.py
import pandas as pd
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator, CCIIndicator
from ta.momentum import StochasticOscillator, RSIIndicator, WilliamsRIndicator
from src.logger import logger
import yfinance as yf
import pandas as pd
import os


def add_macro_economic_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Carrega dados macroeconómicos a partir de ficheiros CSV locais,
    atualiza-os com os dados mais recentes da yfinance, salva-os de volta
    de forma segura e os integra ao DataFrame principal.
    """
    logger.info("Iniciando pipeline de dados macroeconómicos...")
    df_result = df.copy()

    macro_assets = {
        "dxy": {"ticker": "DX-Y.NYB", "path": "data/macro/DXY.csv"},
        "vix": {"ticker": "^VIX", "path": "data/macro/VIX.csv"},
        "gold": {"ticker": "GC=F", "path": "data/macro/GOLD.csv"},
        "tnx": {"ticker": "^TNX", "path": "data/macro/TNX.csv"}
    }
    
    # Define as colunas padrão que queremos em todos os nossos CSVs
    STANDARD_COLUMNS = ['open', 'high', 'low', 'close', 'volume']

    for name, asset_info in macro_assets.items():
        try:
            logger.debug(f"Processando ativo macro: {name.upper()}")
            
            historical_data = pd.DataFrame()
            if os.path.exists(asset_info["path"]):
                try:
                    historical_data = pd.read_csv(asset_info["path"], index_col='date', parse_dates=True)
                    # Garante que as colunas estão no formato padrão
                    historical_data.columns = [col.lower() for col in historical_data.columns]
                except Exception as e:
                    logger.warning(f"Não foi possível ler {asset_info['path']}. Ficheiro pode estar vazio ou corrompido. Será recriado. Erro: {e}")

            last_date = historical_data.index.max() if not historical_data.empty else pd.to_datetime('2018-01-01')
            start_update = last_date + pd.Timedelta(days=1)
            today = pd.to_datetime('today').normalize()

            if start_update <= today:
                logger.debug(f"Buscando novos dados para {name.upper()} de {start_update.date()} até hoje.")
                new_data = yf.download(asset_info["ticker"], start=start_update, end=today, progress=False)
                
                if not new_data.empty:
                    new_data.rename(columns=str.lower, inplace=True)
                    # Concatena e remove duplicados
                    combined_data = pd.concat([historical_data, new_data])
                    combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                    
                    # --- A CORREÇÃO CRÍTICA ESTÁ AQUI ---
                    # Garante que apenas as colunas padrão são mantidas ANTES de salvar
                    final_data_to_save = combined_data[STANDARD_COLUMNS]
                    final_data_to_save.index.name = 'date' # Garante que a coluna de índice tem nome
                    
                    # Salva o ficheiro CSV limpo e correto
                    final_data_to_save.to_csv(asset_info["path"])
                    final_asset_data = final_data_to_save
                else:
                    final_asset_data = historical_data
            else:
                 final_asset_data = historical_data

            if final_asset_data.empty:
                raise ValueError(f"Nenhum dado pôde ser carregado ou baixado para {name.upper()}")

            macro_resampled = final_asset_data['close'].resample('1min').ffill()
            df_result[f'{name}_close_change'] = macro_resampled.pct_change()

        except Exception as e:
            logger.error(f"Falha CRÍTICA ao processar dados para {name.upper()}: {e}", exc_info=True)
            df_result[f'{name}_close_change'] = 0.0

    logger.info("Calculando correlações macro...")
    df_result['btc_dxy_corr_30d'] = df_result['close'].rolling(window=30*1440, min_periods=1440).corr(df_result['dxy_close_change'])
    df_result['btc_vix_corr_30d'] = df_result['close'].rolling(window=30*1440, min_periods=1440).corr(df_result['vix_close_change'])

    cols_to_fill = [f'{name}_close_change' for name in macro_assets.keys()] + ['btc_dxy_corr_30d', 'btc_vix_corr_30d']
    for col in cols_to_fill:
        if col in df_result.columns:
            df_result[col] = df_result[col].fillna(0)

    logger.info("✅ Pipeline de dados macroeconómicos concluído.")
    return df_result

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona um conjunto de indicadores técnicos ao DataFrame."""
    logger.info("Calculando indicadores técnicos...")
    
    # Garante que o DataFrame está ordenado por tempo
    df = df.sort_index()
    
    # Indicadores que já tínhamos
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    
    bb = BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_width'] = bb.bollinger_wband()
    df['bb_pband'] = bb.bollinger_pband()

    macd = MACD(close=df['close'])
    df['macd_diff'] = macd.macd_diff()

    adx = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['adx'] = adx.adx()
    df['adx_power'] = adx.adx_pos() - adx.adx_neg()

    df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
    df['stoch_osc'] = StochasticOscillator(high=df['high'], low=df['low'], close=df['close']).stoch()
    
    # <<< --- ADICIONANDO AS FEATURES QUE FALTAVAM --- >>>
    df['price_change_1m'] = df['close'].pct_change(1)
    df['price_change_5m'] = df['close'].pct_change(5)
    df['momentum_10m'] = df['close'].pct_change(10)
    
    atr_short = df['atr'].rolling(window=5).mean()
    atr_long = df['atr'].rolling(window=100).mean()
    # Adicionamos um epsilon para evitar divisão por zero
    df['volatility_ratio'] = atr_short / (atr_long + 1e-10) 
    
    df['cci'] = CCIIndicator(high=df['high'], low=df['low'], close=df['close'], window=20).cci()
    df['williams_r'] = WilliamsRIndicator(high=df['high'], low=df['low'], close=df['close'], lbp=14).williams_r()
    
    return df

def add_order_flow_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona features baseadas em fluxo de ordens (Order Flow)."""
    logger.info("Calculando features de Fluxo de Ordens (CVD)...")
    
    df['volume_delta'] = df['taker_buy_volume'] - df['taker_sell_volume']
    df['cvd'] = df['volume_delta'].cumsum()
    df['cvd_short_term'] = df['volume_delta'].rolling(window=20).sum()
    
    return df

# CÓDIGO CORRIGIDO para a função add_all_features em src/core/feature_engineering.py

def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Função principal que aplica todas as etapas de engenharia de features.
    """
    df_with_features = df.copy()
    
    # 1. Adiciona indicadores técnicos
    df_with_features = add_technical_indicators(df_with_features)
    
    # 2. Adiciona features de fluxo de ordens
    df_with_features = add_order_flow_features(df_with_features)
    
    # 3. Adiciona as features macroeconómicas (A LINHA QUE FALTAVA)
    df_with_features = add_macro_economic_features(df_with_features)
    
    # 4. Limpeza final de dados
    # Preenche quaisquer valores nulos que os indicadores possam criar no início
    logger.info("Limpando e preenchendo valores nulos restantes...")
    df_with_features = df_with_features.bfill().ffill() # Preenche para frente e para trás
    df_with_features.fillna(0, inplace=True) # Garante que não sobra absolutamente nenhum NaN
    
    logger.info("✅ Engenharia de features concluída.")
    return df_with_features