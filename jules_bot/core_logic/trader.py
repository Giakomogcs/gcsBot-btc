import uuid
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from typing import Optional, Tuple
import time
from jules_bot.database.database_manager import DatabaseManager

class Trader:
    """
    Classe responsável por toda a comunicação com a API da corretora (Binance)
    e por registrar as transações no banco de dados.
    """
    def __init__(self, mode: str = 'trade'):
        self.mode = mode
        self._client = self._init_binance_client()
        self.symbol = config_manager.get('APP', 'symbol')
        self.strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')

        db_config = config_manager.get_section('INFLUXDB')
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"
        # Use the appropriate bucket based on the mode
        if self.mode in ['test', 'backtest']:
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')
        else: # 'trade' or live
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_prices')

        self.db_manager = DatabaseManager(config=db_config)

    def _init_binance_client(self) -> Optional[Client]:
        """Inicializa e autentica o cliente da API da Binance com base no modo."""
        if self.mode == 'offline' or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning("Modo OFFLINE. Trader não se conectará.")
            return None

        use_testnet = self.mode == 'test'

        try:
            if use_testnet:
                binance_config = config_manager.get_section('BINANCE_TESTNET')
            else:
                binance_config = config_manager.get_section('BINANCE_LIVE')

            api_key = binance_config.get('api_key')
            api_secret = binance_config.get('api_secret')

            if not api_key or not api_secret:
                logger.error(f"API Key/Secret da Binance para o modo '{self.mode}' não encontradas.")
                return None

            client = Client(api_key, api_secret, tld='com', testnet=use_testnet)

            try:
                server_time = client.get_server_time()
                local_time = int(time.time() * 1000)
                time_diff = server_time['serverTime'] - local_time
                client.timestamp_offset = time_diff
                logger.info(f"Offset de tempo com o servidor da Binance ajustado em {time_diff} ms.")
            except Exception as e:
                logger.error(f"Não foi possível sincronizar o tempo com a Binance. Erro: {e}", exc_info=True)

            client.ping()
            logger.info(f"✅ Conexão com a Binance estabelecida com sucesso (Modo: {'TESTNET' if use_testnet else 'REAL'}).")
            return client
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"❌ Falha na conexão com a Binance: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ Ocorreu um erro inesperado ao inicializar o cliente Binance: {e}", exc_info=True)
            return None

    def execute_buy(self, amount_usdt: float) -> Tuple[bool, Optional[dict]]:
        """
        Envia uma ordem de compra a mercado e a registra no banco de dados.
        Retorna uma tupla (sucesso, dados_da_ordem).
        """
        if not self._client:
            logger.error("Cliente Binance não inicializado. Ordem de compra não pode ser enviada.")
            return False, None

        trade_id = str(uuid.uuid4())
        try:
            logger.info(f"EXECUTANDO COMPRA: {amount_usdt} USDT de {self.symbol} | Trade ID: {trade_id}")
            order = self._client.order_market_buy(symbol=self.symbol, quoteOrderQty=amount_usdt)
            logger.info(f"✅ ORDEM DE COMPRA EXECUTADA: {order}")

            # Extrair dados para o log
            price = float(order['fills'][0]['price'])
            quantity = float(order['executedQty'])
            usd_value = float(order['cummulativeQuoteQty'])
            commission = sum(float(f['commission']) for f in order['fills'])
            commission_asset = order['fills'][0]['commissionAsset'] if order['fills'] else None

            trade_data = {
                "mode": self.mode,
                "strategy_name": self.strategy_name,
                "symbol": self.symbol,
                "trade_id": trade_id,
                "exchange": "binance_testnet" if self.mode == 'test' else "binance",
                "order_type": "buy",
                "price": price,
                "quantity": quantity,
                "usd_value": usd_value,
                "commission": commission,
                "commission_asset": commission_asset,
                "exchange_order_id": order.get('orderId'),
                "timestamp": pd.to_datetime(order['transactTime'], unit='ms', utc=True)
            }
            self.db_manager.log_trade(trade_data)

            # Adiciona o trade_id ao dicionário de retorno
            order['trade_id'] = trade_id
            return True, order

        except Exception as e:
            logger.error(f"ERRO AO EXECUTAR COMPRA (Trade ID: {trade_id}): {e}", exc_info=True)
            return False, None

    def execute_sell(self, position_data: dict) -> Tuple[bool, Optional[dict]]:
        """
        Envia uma ordem de venda a mercado e a registra no banco de dados.
        Retorna uma tupla (sucesso, dados_da_ordem).
        """
        if not self._client:
            logger.error("Cliente Binance não inicializado. Ordem de venda não pode ser enviada.")
            return False, None

        trade_id = position_data.get('trade_id')
        if not trade_id:
            logger.error("`trade_id` não foi fornecido para a venda. Abortando.")
            return False, None

        try:
            quantity_to_sell = position_data.get('quantity')
            logger.info(f"EXECUTANDO VENDA: {quantity_to_sell} de {self.symbol} | Trade ID: {trade_id}")
            order = self._client.order_market_sell(symbol=self.symbol, quantity=quantity_to_sell)
            logger.info(f"✅ ORDEM DE VENDA EXECUTADA: {order}")

            # Extrair dados para o log
            price = float(order['fills'][0]['price'])
            quantity = float(order['executedQty'])
            usd_value = float(order['cummulativeQuoteQty'])
            commission = sum(float(f['commission']) for f in order['fills'])
            commission_asset = order['fills'][0]['commissionAsset'] if order['fills'] else None

            trade_data = {
                "mode": self.mode,
                "strategy_name": self.strategy_name,
                "symbol": self.symbol,
                "trade_id": trade_id,
                "exchange": "binance_testnet" if self.mode == 'test' else "binance",
                "order_type": "sell",
                "price": price,
                "quantity": quantity,
                "usd_value": usd_value,
                "commission": commission,
                "commission_asset": commission_asset,
                "exchange_order_id": order.get('orderId'),
                "realized_pnl": position_data.get("realized_pnl"), # Deve ser calculado e passado em `position_data`
                "held_quantity": position_data.get("held_quantity"), # Deve ser calculado e passado em `position_data`
                "timestamp": pd.to_datetime(order['transactTime'], unit='ms', utc=True)
            }
            self.db_manager.log_trade(trade_data)

            order['trade_id'] = trade_id
            return True, order

        except Exception as e:
            logger.error(f"ERRO AO EXECUTAR VENDA (Trade ID: {trade_id}): {e}", exc_info=True)
            return False, None

    def close_connection(self):
        """Closes the connection to the exchange."""
        if self._client:
            self._client.close_connection()
            logger.info("Conexão com a Binance fechada.")
