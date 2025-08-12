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
        self.client = self._init_binance_client()
        self.symbol = config_manager.get('APP', 'symbol')
        self.strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')

        db_config = config_manager.get_db_config()

        if self.mode == 'trade':
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_live')
        elif self.mode == 'test':
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_testnet')
        elif self.mode == 'backtest':
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')
        else:
            db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_prices') # Fallback

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
                mode_name = 'TESTNET' if use_testnet else 'LIVE'
                key_name = 'BINANCE_TESTNET_API_KEY' if use_testnet else 'BINANCE_API_KEY'
                secret_name = 'BINANCE_TESTNET_API_SECRET' if use_testnet else 'BINANCE_API_SECRET'

                error_msg = (
                    f"Binance API Key/Secret for '{mode_name}' mode not found.\n"
                    f"Please ensure the following environment variables are set in your .env file:\n"
                    f"  - {key_name}\n"
                    f"  - {secret_name}"
                )
                logger.error(error_msg)
                raise ValueError(error_msg)
            
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
        return self.client is not None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Fetches the current price for a symbol from Binance."""
        if not self.is_ready:
            logger.warning("Trader is not ready. Cannot fetch current price.")
            return None
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"API error fetching current price for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching current price for {symbol}: {e}")
            return None

    def get_all_prices(self) -> dict:
        """Fetches the latest price for all symbols."""
        if not self.is_ready:
            logger.warning("Trader is not ready. Cannot fetch prices.")
            return {}
        try:
            prices = self.client.get_all_tickers()
            return {item['symbol']: float(item['price']) for item in prices}
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"API error fetching all prices: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error fetching all prices: {e}")
            return {}

    def get_account_balance(self, asset: str = 'USDT') -> float:
        """Fetches the free balance for a specific asset from the account."""
        if not self.is_ready:
            logger.warning("Trader is not ready. Cannot fetch account balance.")
            return 0.0
        try:
            account_info = self.client.get_account()
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

    def _parse_order_response(self, order: Dict[str, Any], trade_id: str, decision_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parses a Binance order response to extract accurate trade details.
        Calculates the volume-weighted average price (VWAP) from the 'fills'.
        """
        if not order.get('fills'):
            logger.warning(f"Order {order.get('orderId')} has no fills. Cannot parse trade details.")
            # Return a structure with zeros to avoid downstream errors, but log a clear warning.
            return {
                "trade_id": trade_id, "symbol": self.symbol, "price": 0.0, "quantity": 0.0,
                "usd_value": 0.0, "commission": 0.0, "commission_asset": "N/A",
                "exchange_order_id": str(order.get('orderId')), "timestamp": order.get('transactTime'),
                "decision_context": decision_context, "environment": self.environment
            }

        executed_qty = float(order['executedQty'])
        cummulative_quote_qty = float(order['cummulativeQuoteQty'])

        # Calculate Volume-Weighted Average Price (VWAP)
        # This is the most accurate representation of the execution price.
        price = cummulative_quote_qty / executed_qty if executed_qty > 0 else 0.0

        # Sum commissions from all fills
        commission = sum(float(f.get('commission', 0.0)) for f in order['fills'])
        commission_asset = order['fills'][0].get('commissionAsset', 'N/A') if order['fills'] else 'N/A'

        # Return a standardized dictionary
        return {
            "trade_id": trade_id,
            "symbol": self.symbol,
            "price": price,
            "quantity": executed_qty,
            "usd_value": cummulative_quote_qty,
            "commission": commission,
            "commission_asset": commission_asset,
            "exchange_order_id": str(order.get('orderId')),
            "timestamp": order.get('transactTime'),
            "decision_context": decision_context,
            "environment": self.environment
        }


    def execute_buy(self, amount_usdt: float, run_id: str, decision_context: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[dict]]:
        """
        Submits a market buy order and returns a standardized trade result dictionary.
        """
        if not self.client:
            logger.error("Binance client not initialized. Buy order cannot be submitted.")
            return False, None

        trade_id = str(uuid.uuid4())
        try:
            logger.info(f"EXECUTING BUY: {amount_usdt} USDT of {self.symbol} | Trade ID: {trade_id}")
            order = self.client.order_market_buy(symbol=self.symbol, quoteOrderQty=amount_usdt)
            logger.info(f"✅ BUY ORDER EXECUTED: {order}")

            # Parse the response to get accurate, standardized data
            trade_result = self._parse_order_response(order, trade_id, decision_context)

            return True, trade_result

        except Exception as e:
            logger.error(f"ERROR EXECUTING BUY (Trade ID: {trade_id}): {e}", exc_info=True)
            return False, None

    def execute_sell(self, position_data: dict, run_id: str, decision_context: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[dict]]:
        """
        Submits a market sell order and returns a standardized trade result dictionary.
        """
        if not self.client:
            logger.error("Binance client not initialized. Sell order cannot be submitted.")
            return False, None

        trade_id = position_data.get('trade_id')
        if not trade_id:
            logger.error("'trade_id' not provided for sell order. Aborting.")
            return False, None

        try:
            quantity_to_sell = position_data.get('quantity')
            logger.info(f"EXECUTING SELL: {quantity_to_sell:.8f} of {self.symbol} | Trade ID: {trade_id}")
            order = self.client.order_market_sell(symbol=self.symbol, quantity=quantity_to_sell)
            logger.info(f"✅ SELL ORDER EXECUTED: {order}")

            # Parse the response to get accurate, standardized data
            trade_result = self._parse_order_response(order, trade_id, decision_context)

            # Add PnL info from the input data, as the trader doesn't know this
            trade_result.update({
                "commission_usd": position_data.get("commission_usd"),
                "realized_pnl_usd": position_data.get("realized_pnl_usd"),
                "hodl_asset_amount": position_data.get("hodl_asset_amount"),
                "hodl_asset_value_at_sell": position_data.get("hodl_asset_value_at_sell")
            })

            return True, trade_result

        except Exception as e:
            logger.error(f"ERROR EXECUTING SELL (Trade ID: {trade_id}): {e}", exc_info=True)
            return False, None

    def close_connection(self):
        """Closes the connection to the exchange."""
        if self._client:
            self._client.close_connection()
            logger.info("Connection to Binance closed.")
