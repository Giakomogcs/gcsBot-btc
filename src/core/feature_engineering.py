# src/core/feature_engineering.py
import pandas as pd
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, ADXIndicator, CCIIndicator
from ta.momentum import StochasticOscillator, RSIIndicator, WilliamsRIndicator
from src.logger import logger
import yfinance as yf
import pandas as pd
import os
from src.logger import logger # Garanta que o logger está importado no topo do ficheiro

def add_macro_economic_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Carrega dados macroeconómicos a partir de ficheiros CSV locais,
    atualiza-os com os dados mais recentes da yfinance, salva-os de volta
    e os integra ao DataFrame principal.
    """
    logger.info("Iniciando pipeline de dados macroeconómicos...")
    df_result = df.copy()

    # Mapeia o nome do nosso ativo para o ticker do Yahoo Finance e o caminho do ficheiro local
    macro_assets = {
        "dxy": {"ticker": "DX-Y.NYB", "path": "data/macro/dxy.csv"},
        "vix": {"ticker": "^VIX", "path": "data/macro/vix.csv"},
        "gold": {"ticker": "GC=F", "path": "data/macro/gold.csv"},
        "tnx": {"ticker": "^TNX", "path": "data/macro/tnx.csv"}
    }
    
    for name, asset_info in macro_assets.items():
        try:
            logger.debug(f"Processando ativo macro: {name.upper()}")
            
            # 1. Carregar o histórico local do CSV
            if not os.path.exists(asset_info["path"]):
                logger.warning(f"Ficheiro histórico para {name.upper()} não encontrado em {asset_info['path']}. Tentando baixar tudo.")
                historical_data = pd.DataFrame()
            else:
                historical_data = pd.read_csv(asset_info["path"], index_col='date', parse_dates=True)
            
            # 2. Determinar a data de início para buscar novos dados
            if not historical_data.empty:
                last_date = historical_data.index.max()
                start_update = last_date + pd.Timedelta(days=1)
            else:
                # Se não há histórico, busca desde o início dos dados do BTC
                start_update = df.index.min()

            # 3. Baixar apenas os dados novos
            today = pd.to_datetime('today') + pd.Timedelta(days=1)
            if start_update < today:
                logger.debug(f"Buscando novos dados para {name.upper()} de {start_update.date()} até hoje.")
                new_data = yf.download(asset_info["ticker"], start=start_update, end=today, progress=False)
                
                # 4. Combinar e salvar de volta no CSV
                if not new_data.empty:
                    # Renomeia as colunas para o nosso padrão (lowercase)
                    new_data.rename(columns=str.lower, inplace=True)
                    # Mantém apenas as colunas que nos interessam
                    new_data = new_data[['open', 'high', 'low', 'close', 'volume']]
                    
                    combined_data = pd.concat([historical_data, new_data])
                    # Remove duplicados, mantendo os dados mais recentes
                    combined_data = combined_data[~combined_data.index.duplicated(keep='last')]
                    combined_data.to_csv(asset_info["path"])
                    final_asset_data = combined_data
                else:
                    final_asset_data = historical_data
            else:
                 final_asset_data = historical_data

            if final_asset_data.empty:
                raise ValueError(f"Nenhum dado pôde ser carregado ou baixado para {name.upper()}")

            # 5. Integrar ao DataFrame principal do bot
            # Reamostra os dados (geralmente diários) para 1 minuto, preenchendo os valores
            macro_resampled = final_asset_data['close'].resample('1min').ffill()
            df_result[f'{name}_close_change'] = macro_resampled.pct_change()

        except Exception as e:
            logger.error(f"Falha CRÍTICA ao processar dados para {name.upper()}: {e}", exc_info=True)
            df_result[f'{name}_close_change'] = 0.0

    # O cálculo de correlação continua igual
    logger.info("Calculando correlações macro...")
    df_result['btc_dxy_corr_30d'] = df_result['close'].rolling(window=30*1440, min_periods=1440).corr(df_result['dxy_close_change'])
    df_result['btc_vix_corr_30d'] = df_result['close'].rolling(window=30*1440, min_periods=1440).corr(df_result['vix_close_change'])

    # Preenchemos os valores nulos que sobram no final
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