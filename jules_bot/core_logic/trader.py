import uuid
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from typing import Optional, Tuple, Dict, Any
import time
from jules_bot.database.database_manager import DatabaseManager

class Trader:
    """
    Handles all communication with the exchange API (Binance) and records
    transactions in the database.
    """
    def __init__(self, mode: str = 'trade'):
        self.mode = mode
        self.environment = self._map_mode_to_environment(mode)
        self._client = self._init_binance_client()
        self.symbol = config_manager.get('APP', 'symbol')
        self.strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')

        db_config = config_manager.get_section('INFLUXDB')
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"

        if self.mode in ['test', 'backtest']:
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')
        else:
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_prices')

        self.db_manager = DatabaseManager(config=db_config)

    def _map_mode_to_environment(self, mode: str) -> str:
        """Maps the internal 'mode' to the user-facing 'environment' tag."""
        if mode == 'backtest':
            return 'backtest'
        elif mode == 'test':
            return 'paper_trade'
        elif mode == 'trade':
            return 'live_trade'
        return 'unknown'

    def _init_binance_client(self) -> Optional[Client]:
        """Initializes and authenticates the Binance API client based on the mode."""
        if self.mode == 'offline' or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning("OFFLINE mode. Trader will not connect.")
            return None

        use_testnet = self.mode == 'test'

        try:
            binance_config = config_manager.get_section('BINANCE_TESTNET' if use_testnet else 'BINANCE_LIVE')
            api_key = binance_config.get('api_key')
            api_secret = binance_config.get('api_secret')

            if not api_key or not api_secret:
                logger.error(f"Binance API Key/Secret for '{self.mode}' mode not found.")
                return None
            
            requests_params = {"timeout": 30}
            client = Client(api_key, api_secret, tld='com', testnet=use_testnet, requests_params=requests_params)

            try:
                server_time = client.get_server_time()
                local_time = int(time.time() * 1000)
                time_diff = server_time['serverTime'] - local_time
                client.timestamp_offset = time_diff
                logger.info(f"Timestamp offset with Binance server adjusted by {time_diff} ms.")
            except Exception as e:
                logger.error(f"Could not sync time with Binance. Error: {e}", exc_info=True)

            client.ping()
            logger.info(f"✅ Successfully connected to Binance (Mode: {'TESTNET' if use_testnet else 'LIVE'}).")
            return client
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"❌ Binance connection failed: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ An unexpected error occurred while initializing the Binance client: {e}", exc_info=True)
            return None

    @property
    def is_ready(self) -> bool:
        """Returns True if the Binance client is initialized and ready."""
        return self._client is not None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Fetches the current price for a symbol from Binance."""
        if not self.is_ready:
            logger.warning("Trader is not ready. Cannot fetch current price.")
            return None
        try:
            ticker = self._client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"API error fetching current price for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching current price for {symbol}: {e}")
            return None

    def get_account_balance(self, asset: str = 'USDT') -> float:
        """Fetches the free balance for a specific asset from the account."""
        if not self.is_ready:
            logger.warning("Trader is not ready. Cannot fetch account balance.")
            return 0.0
        try:
            account_info = self._client.get_account()
            for balance in account_info['balances']:
                if balance['asset'] == asset:
                    return float(balance['free'])
            return 0.0
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"API error fetching account balance for {asset}: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Unexpected error fetching account balance for {asset}: {e}")
            return 0.0

    def execute_buy(self, amount_usdt: float, run_id: str, decision_context: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[dict]]:
        """
        Submits a market buy order and records it in the database.
        Returns a tuple (success, order_data).
        """
        if not self._client:
            logger.error("Binance client not initialized. Buy order cannot be submitted.")
            return False, None

        trade_id = str(uuid.uuid4())
        try:
            logger.info(f"EXECUTING BUY: {amount_usdt} USDT of {self.symbol} | Trade ID: {trade_id}")
            order = self._client.order_market_buy(symbol=self.symbol, quoteOrderQty=amount_usdt)
            logger.info(f"✅ BUY ORDER EXECUTED: {order}")

            price = float(order['fills'][0]['price'])
            quantity = float(order['executedQty'])
            usd_value = float(order['cummulativeQuoteQty'])
            commission = sum(float(f['commission']) for f in order['fills'])
            commission_asset = order['fills'][0]['commissionAsset'] if order['fills'] else 'N/A'

            from jules_bot.core.schemas import TradePoint
            import pandas as pd

            trade_point = TradePoint(
                run_id=run_id,
                environment=self.environment,
                strategy_name=self.strategy_name,
                symbol=self.symbol,
                trade_id=trade_id,
                exchange="binance_testnet" if self.mode == 'test' else "binance_live",
                order_type="buy",
                price=price,
                quantity=quantity,
                usd_value=usd_value,
                commission=commission,
                commission_asset=commission_asset,
                exchange_order_id=order.get('orderId'),
                timestamp=pd.to_datetime(order['transactTime'], unit='ms', utc=True).to_pydatetime(),
                decision_context=decision_context
            )
            self.db_manager.log_trade(trade_point)

            order['trade_id'] = trade_id
            order['environment'] = self.environment # Add environment to the result
            return True, order

        except Exception as e:
            logger.error(f"ERROR EXECUTING BUY (Trade ID: {trade_id}): {e}", exc_info=True)
            return False, None

    def execute_sell(self, position_data: dict, run_id: str, decision_context: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[dict]]:
        """
        Submits a market sell order and records it in the database.
        Returns a tuple (success, order_data).
        """
        if not self._client:
            logger.error("Binance client not initialized. Sell order cannot be submitted.")
            return False, None

        trade_id = position_data.get('trade_id')
        if not trade_id:
            logger.error("'trade_id' not provided for sell order. Aborting.")
            return False, None

        try:
            quantity_to_sell = position_data.get('quantity')
            logger.info(f"EXECUTING SELL: {quantity_to_sell} of {self.symbol} | Trade ID: {trade_id}")
            order = self._client.order_market_sell(symbol=self.symbol, quantity=quantity_to_sell)
            logger.info(f"✅ SELL ORDER EXECUTED: {order}")

            price = float(order['fills'][0]['price'])
            quantity = float(order['executedQty'])
            usd_value = float(order['cummulativeQuoteQty'])
            commission = sum(float(f['commission']) for f in order['fills'])
            commission_asset = order['fills'][0]['commissionAsset'] if order['fills'] else 'N/A'

            from jules_bot.core.schemas import TradePoint
            import pandas as pd

            trade_point = TradePoint(
                run_id=run_id,
                environment=self.environment,
                strategy_name=self.strategy_name,
                symbol=self.symbol,
                trade_id=trade_id,
                exchange="binance_testnet" if self.mode == 'test' else "binance_live",
                order_type="sell",
                price=price,
                quantity=quantity,
                usd_value=usd_value,
                commission=commission,
                commission_asset=commission_asset,
                exchange_order_id=order.get('orderId'),
                timestamp=pd.to_datetime(order['transactTime'], unit='ms', utc=True).to_pydatetime(),
                decision_context=decision_context,
                commission_usd=position_data.get("commission_usd"),
                realized_pnl_usd=position_data.get("realized_pnl_usd"),
                hodl_asset_amount=position_data.get("hodl_asset_amount"),
                hodl_asset_value_at_sell=position_data.get("hodl_asset_value_at_sell")
            )
            self.db_manager.log_trade(trade_point)

            order['trade_id'] = trade_id
            order['environment'] = self.environment # Add environment to the result
            return True, order

        except Exception as e:
            logger.error(f"ERROR EXECUTING SELL (Trade ID: {trade_id}): {e}", exc_info=True)
            return False, None

    def close_connection(self):
        """Closes the connection to the exchange."""
        if self._client:
            self._client.close_connection()
            logger.info("Connection to Binance closed.")
