import threading
from flask import Flask, request, jsonify
from decimal import Decimal, InvalidOperation
from jules_bot.utils.logger import logger

class ApiServer:
    def __init__(self, trader, state_manager, strategy_rules, bot_id, min_trade_size):
        self.app = Flask(__name__)
        self.trader = trader
        self.state_manager = state_manager
        self.strategy_rules = strategy_rules
        self.bot_id = bot_id
        self.min_trade_size = min_trade_size

        self.app.route("/force_buy", methods=["POST"])(self.force_buy)
        self.app.route("/force_sell", methods=["POST"])(self.force_sell)
        self.app.route("/health", methods=["GET"])(self.health_check)

    def health_check(self):
        return jsonify({"status": "ok"}), 200

    def force_buy(self):
        data = request.get_json()
        if not data or "amount_usd" not in data:
            return jsonify({"status": "error", "message": "Missing 'amount_usd' in request body."}), 400

        try:
            amount_usd = Decimal(data["amount_usd"])
        except InvalidOperation:
            return jsonify({"status": "error", "message": "Invalid number format for 'amount_usd'."}), 400

        logger.info(f"[API] Received force_buy command for ${amount_usd:.2f}")

        if amount_usd <= 0:
            return jsonify({"status": "error", "message": "Buy amount must be positive."}), 400

        if amount_usd < self.min_trade_size:
            message = f"Manual buy for ${amount_usd:.2f} is below the minimum trade size of ${self.min_trade_size:.2f}."
            logger.error(f"[API] {message}")
            return jsonify({"status": "error", "message": message}), 400

        success, buy_result = self.trader.execute_buy(amount_usd, self.bot_id, {"reason": "manual_override_api"})
        if success:
            purchase_price = Decimal(buy_result.get('price'))
            sell_target_price = self.strategy_rules.calculate_sell_target_price(purchase_price)
            self.state_manager.create_new_position(buy_result, sell_target_price)
            message = f"Successfully executed manual buy for ${amount_usd:.2f}."
            logger.info(f"[API] {message}")
            return jsonify({"status": "success", "message": message, "trade_details": buy_result}), 200
        else:
            message = f"Failed to execute manual buy for ${amount_usd:.2f}. Reason: {buy_result.get('message', 'Unknown error from trader')}"
            logger.error(f"[API] {message}")
            return jsonify({"status": "error", "message": message}), 500

    def force_sell(self):
        data = request.get_json()
        if not data or "trade_id" not in data:
            return jsonify({"status": "error", "message": "Missing 'trade_id' in request body."}), 400

        trade_id = data["trade_id"]
        logger.info(f"[API] Received force_sell command for trade_id: {trade_id}")

        position = self.state_manager.get_position_by_id(trade_id)
        if not position:
            message = f"Cannot force sell: Trade with ID '{trade_id}' not found in open positions."
            logger.error(f"[API] {message}")
            return jsonify({"status": "error", "message": message}), 404

        # For now, we assume selling 100% of the position
        quantity_to_sell = Decimal(str(position.quantity))

        # Notional value check
        current_price_str = self.trader.get_current_price(self.trader.symbol)
        if current_price_str:
            current_price = Decimal(current_price_str)
            notional_value = quantity_to_sell * current_price
            if notional_value < self.trader.min_notional:
                message = f"Notional value (${notional_value:,.2f}) is below exchange minimum (${self.trader.min_notional:,.2f})."
                logger.error(f"[API] {message}")
                return jsonify({"status": "error", "message": message}), 400
        else:
            logger.warning("[API] Could not fetch price to validate notional value for force sell.")

        sell_position_data = position.to_dict()
        success, sell_result = self.trader.execute_sell(sell_position_data, self.bot_id, {"reason": "manual_force_sell_api"})
        if success:
            buy_price = Decimal(str(position.price))
            sell_price = Decimal(str(sell_result.get('price', '0')))
            sell_commission_usd = Decimal(str(sell_result.get('commission_usd', '0')))

            realized_pnl_usd = self.strategy_rules.calculate_realized_pnl(
                buy_price=buy_price, sell_price=sell_price, quantity_sold=quantity_to_sell,
                buy_commission_usd=Decimal(str(position.commission_usd or '0')),
                sell_commission_usd=sell_commission_usd,
                buy_quantity=Decimal(str(position.quantity))
            )
            self.state_manager.close_forced_position(trade_id, sell_result, realized_pnl_usd)
            message = f"Successfully executed force sell for trade {trade_id}."
            logger.info(f"[API] {message}")
            return jsonify({"status": "success", "message": message, "trade_details": sell_result}), 200
        else:
            message = f"Failed to execute force sell for trade {trade_id}. Reason: {sell_result.get('message', 'Unknown error from trader')}"
            logger.error(f"[API] {message}")
            return jsonify({"status": "error", "message": message}), 500

    def run(self):
        # Use a different port to avoid conflicts
        self.app.run(host="0.0.0.0", port=5001, debug=False)

    def start_server_in_thread(self):
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        logger.info("API server started in a background thread.")
