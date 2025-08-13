# src/core/account_manager.py (VERSÃO CORRIGIDA)

from binance.client import Client
from binance.exceptions import BinanceAPIException
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager

class AccountManager:
    def __init__(self, binance_client: Client):
        self.client = binance_client
        self.base_asset = "BTC"
        self.quote_asset = config_manager.get('APP', 'symbol').replace("BTC", "")

    def get_base_asset_balance(self) -> float:
        """Busca o saldo livre do ativo base (ex: BTC) na conta da Binance."""
        if not self.client:
            logger.warning("Cliente Binance não disponível (modo offline). Retornando saldo 0.")
            return 0.0
        try:
            account_info = self.client.get_account()
            balance_info = next(
                (item for item in account_info['balances'] if item['asset'] == self.base_asset),
                None
            )
            if balance_info:
                return float(balance_info['free'])
            else:
                logger.warning(f"Ativo {self.base_asset} não encontrado na conta.")
                return 0.0
        except BinanceAPIException as e:
            logger.error(f"Erro na API da Binance ao buscar saldo de BTC: {e}", exc_info=True)
            return 0.0
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar saldo de BTC: {e}", exc_info=True)
            return 0.0
        
    def _format_quantity_for_symbol(self, symbol: str, quantity: float, current_price: float) -> float:
        """
        Formata a quantidade para a precisão correta (LOT_SIZE) e valida
        o valor mínimo da ordem (MIN_NOTIONAL).
        Retorna 0.0 se a validação falhar.
        """
        try:
            logger.info(f"Buscando filtros de negociação para o símbolo {symbol}...")
            info = self.client.get_exchange_info()
            symbol_info = next((s for s in info['symbols'] if s['symbol'] == symbol), None)
            if not symbol_info:
                logger.error(f"Não foi possível encontrar informações para o símbolo {symbol}.")
                return 0.0

            # 1. Validação do MIN_NOTIONAL (Valor Mínimo da Ordem)
            min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
            # Usamos 5.0 como um padrão seguro caso a API não retorne o valor.
            min_notional_value = float(min_notional_filter.get('minNotional', '5.0')) if min_notional_filter else 5.0
            
            order_value = quantity * current_price
            if order_value < min_notional_value:
                logger.warning(
                    f"Ordem de venda IGNORADA. O valor da ordem ({order_value:.2f} USDT) "
                    f"é menor que o mínimo exigido de {min_notional_value:.2f} USDT."
                )
                return 0.0 # Retorna 0 para indicar que a ordem não deve ser enviada

            # 2. Formatação da precisão (LOT_SIZE)
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if not lot_size_filter:
                logger.error(f"Não foi possível encontrar o filtro LOT_SIZE para {symbol}.")
                return 0.0

            step_size = lot_size_filter.get('stepSize')
            precision = step_size.find('1') - 1
            if precision < 0:
                precision = 0
            
            # Formata a quantidade truncando (mais seguro que arredondar)
            formatted_quantity = int(quantity * (10 ** precision)) / (10 ** precision)
            logger.info(f"Quantidade original: {quantity}, Quantidade formatada: {formatted_quantity}")
            
            # Garante que mesmo após formatar, a quantidade não seja zero
            if formatted_quantity <= 0:
                 logger.warning(f"Após formatação, a quantidade resultou em {formatted_quantity}. Ignorando ordem.")
                 return 0.0
                 
            return formatted_quantity

        except Exception as e:
            logger.error(f"Falha crítica ao formatar/validar a quantidade para o símbolo {symbol}: {e}", exc_info=True)
            return 0.0

    def get_quote_asset_balance(self) -> float:
        """
        Busca o saldo livre do ativo de cotação (ex: USDT) na conta da Binance.
        Esta versão foi corrigida para funcionar corretamente tanto em modo real quanto testnet.
        """
        # Se o cliente não foi inicializado (modo offline), não há o que fazer.
        if not self.client:
            logger.warning("Cliente Binance não disponível (modo offline). Retornando saldo 100")
            return 100

        try:
            # Esta chamada funciona tanto para a conta real quanto para a testnet,
            # dependendo de como o 'self.client' foi inicializado.
            account_info = self.client.get_account()
            
            # Procura o ativo de cotação (ex: USDT) nos saldos da conta.
            balance_info = next(
                (item for item in account_info['balances'] if item['asset'] == self.quote_asset),
                None
            )
            
            if balance_info:
                free_balance = float(balance_info['free'])
                logger.debug(f"Saldo de {self.quote_asset} consultado: {free_balance}")
                return free_balance
            else:
                logger.warning(f"Ativo {self.quote_asset} não encontrado na conta.")
                return 0.0
        except BinanceAPIException as e:
            logger.error(f"Erro na API da Binance ao buscar saldo: {e}", exc_info=True)
            return 0.0
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar saldo: {e}", exc_info=True)
            return 0.0

    def update_on_sell(self, quantity_btc: float, current_price: float):
        """
        Places a market sell order on Binance after full validation.
        """
        if not self.client or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning(f"OFFLINE MODE: Simulating sell of {quantity_btc:.8f} BTC.")
            return {"status": "FILLED"} # Simula uma ordem bem-sucedida

        try:
            # Valida e formata a quantidade usando a nova função robusta
            formatted_quantity = self._format_quantity_for_symbol(
                symbol=config_manager.get('APP', 'symbol'),
                quantity=quantity_btc, 
                current_price=current_price
            )
            
            # Apenas tenta vender se a quantidade for válida (maior que zero)
            if formatted_quantity > 0:
                logger.info(f"Attempting to place market SELL order for {formatted_quantity:.8f} BTC...")
                order = self.client.order_market_sell(symbol=config_manager.get('APP', 'symbol'), quantity=formatted_quantity)
                logger.info(f"SUCCESS: Market SELL order placed: {order}")
                return order # Retorna a ordem para o PositionManager
            else:
                # A razão já foi logada dentro de _format_quantity_for_symbol
                logger.info("A ordem de venda não prosseguiu após validação.")
                return None # Indica que nenhuma ordem foi criada

        except BinanceAPIException as e:
            logger.error(f"Binance API Error on SELL: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error on SELL: {e}", exc_info=True)
            return None

    def update_on_buy(self, quote_order_qty: float):
        """
        Places a market buy order on Binance.
        """
        if not self.client or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning(f"OFFLINE MODE: Simulating buy with {quote_order_qty:.2f} USDT.")
            return True # Simulate success

        try:
            rounded_qty = round(quote_order_qty, 2)
            logger.info(f"Attempting to place market BUY order for {rounded_qty:.2f} USDT...")
            order = self.client.order_market_buy(symbol=config_manager.get('APP', 'symbol'), quoteOrderQty=rounded_qty)
            logger.info(f"SUCCESS: Market BUY order placed: {order}")
            return True
        except BinanceAPIException as e:
            logger.error(f"Binance API Error on BUY: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error on BUY: {e}", exc_info=True)
            return False

    def get_open_orders(self) -> list:
        """
        Fetches open orders from Binance for the current symbol.
        """
        if not self.client or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning("OFFLINE MODE: Cannot fetch open orders.")
            return []

        try:
            open_orders = self.client.get_open_orders(symbol=config_manager.get('APP', 'symbol'))
            return open_orders
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching open orders: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching open orders: {e}", exc_info=True)
            return []

    def get_trade_history(self, limit: int = 10) -> list:
        """
        Fetches trade history from Binance for the current symbol.
        """
        if not self.client or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning("OFFLINE MODE: Cannot fetch trade history.")
            return []

        try:
            trades = self.client.get_my_trades(symbol=config_manager.get('APP', 'symbol'), limit=limit)
            return trades
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching trade history: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching trade history: {e}", exc_info=True)
            return []

    def get_all_my_trades(self, symbol: str, from_id: int = 0) -> list:
        """
        Fetches all historical trades for a symbol, starting from a specific trade ID.
        """
        if not self.client or config_manager.getboolean('APP', 'force_offline_mode'):
            logger.warning("OFFLINE MODE: Cannot fetch all trades.")
            return []

        try:
            all_trades = []
            limit = 1000  # Max limit per request
            last_id = from_id

            while True:
                logger.info(f"Fetching trades for {symbol} starting from id {last_id}...")
                trades = self.client.get_my_trades(symbol=symbol, fromId=last_id, limit=limit)

                if not trades:
                    break

                all_trades.extend(trades)
                last_id = trades[-1]['id'] + 1

                # If the number of trades fetched is less than the limit, we've reached the end
                if len(trades) < limit:
                    break

            logger.info(f"Fetched a total of {len(all_trades)} new trades for {symbol}.")
            return all_trades
        except BinanceAPIException as e:
            logger.error(f"Binance API Error fetching all trades for {symbol}: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching all trades for {symbol}: {e}", exc_info=True)
            return []

    def get_all_account_balances(self, all_prices: dict) -> list:
        """
        Fetches all non-zero asset balances and calculates their USD value.
        """
        if not self.client:
            logger.warning("Binance client not available (offline mode). Returning empty list.")
            return []
        try:
            account_info = self.client.get_account()
            non_zero_balances = []
            for balance in account_info['balances']:
                free_balance = float(balance['free'])
                locked_balance = float(balance['locked'])
                total_balance = free_balance + locked_balance

                if total_balance > 0:
                    asset = balance['asset']
                    usd_value = 0.0

                    # Calculate USD value
                    if asset == 'USDT':
                        usd_value = total_balance
                    else:
                        pair = f"{asset}USDT"
                        if pair in all_prices:
                            usd_value = total_balance * all_prices[pair]

                    balance['usd_value'] = usd_value
                    non_zero_balances.append(balance)

            return non_zero_balances
        except BinanceAPIException as e:
            logger.error(f"Binance API error fetching all account balances: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching all account balances: {e}", exc_info=True)
            return []