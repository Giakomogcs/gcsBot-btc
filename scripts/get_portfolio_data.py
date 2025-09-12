import json
import sys
import os
import datetime
import logging
from decimal import Decimal

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.portfolio_manager import PortfolioManager
from jules_bot.database.postgres_manager import PostgresManager

def get_portfolio_data():
    """
    Fetches the latest portfolio snapshot, historical data, and DCOM status for the TUI.
    """
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        print(json.dumps({"error": "BOT_NAME environment variable not set."}), file=sys.stderr)
        sys.exit(1)

    try:
        # 1. Initialize ConfigManager
        config_manager.initialize(bot_name)

        # 2. Instantiate services
        db_manager = PostgresManager()
        portfolio_manager = PortfolioManager(db_manager.SessionLocal)

        # --- Fetch Data ---
        latest_snapshot = portfolio_manager.get_latest_snapshot()
        portfolio_history = portfolio_manager.get_portfolio_history(limit=50)

        # --- DCOM Status Calculation ---
        dcom_data = {}
        if latest_snapshot:
            # Use Decimal for all financial calculations
            total_equity = Decimal(latest_snapshot.total_portfolio_value_usd)
            open_positions_value = Decimal(latest_snapshot.open_positions_value_usd)

            wc_percentage = Decimal(config_manager.get('STRATEGY_RULES', 'working_capital_percentage', fallback='0.8'))

            working_capital_target = total_equity * wc_percentage
            strategic_reserve = total_equity - working_capital_target
            capital_in_use = open_positions_value
            working_capital_remaining = working_capital_target - capital_in_use

            # Determine Operating Mode
            if working_capital_target > 0:
                usage_percent = (capital_in_use / working_capital_target) * 100
                operating_mode = "Aggressive" if usage_percent > 50 else "Conservative"
            else:
                operating_mode = "N/A"

            dcom_data = {
                "total_equity": f"{total_equity:.2f}",
                "working_capital_target": f"{working_capital_target:.2f}",
                "working_capital_in_use": f"{capital_in_use:.2f}",
                "working_capital_remaining": f"{working_capital_remaining:.2f}",
                "strategic_reserve": f"{strategic_reserve:.2f}",
                "operating_mode": operating_mode
            }
        else:
            dcom_data = {
                "total_equity": "0.00",
                "working_capital_target": "0.00",
                "working_capital_in_use": "0.00",
                "working_capital_remaining": "0.00",
                "strategic_reserve": "0.00",
                "operating_mode": "N/A"
            }

        # --- Prepare data for JSON serialization ---
        if latest_snapshot:
            latest_snapshot_data = {
                "id": latest_snapshot.id,
                "timestamp": latest_snapshot.timestamp.isoformat(),
                "total_portfolio_value_usd": f"{Decimal(latest_snapshot.total_portfolio_value_usd):.2f}",
                "usd_balance": f"{Decimal(latest_snapshot.usd_balance):.2f}",
                "open_positions_value_usd": f"{Decimal(latest_snapshot.open_positions_value_usd):.2f}",
                "realized_pnl_usd": f"{Decimal(latest_snapshot.realized_pnl_usd):.2f}",
                "btc_treasury_amount": f"{Decimal(latest_snapshot.btc_treasury_amount):.8f}",
                "btc_treasury_value_usd": f"{Decimal(latest_snapshot.btc_treasury_value_usd):.2f}",
                "evolution_percent_vs_previous": f"{Decimal(latest_snapshot.evolution_percent_vs_previous or 0):.2f}"
            }
        else:
            latest_snapshot_data = {
                "id": 0,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "total_portfolio_value_usd": "0.00",
                "usd_balance": "0.00",
                "open_positions_value_usd": "0.00",
                "realized_pnl_usd": "0.00",
                "btc_treasury_amount": "0.00000000",
                "btc_treasury_value_usd": "0.00",
                "evolution_percent_vs_previous": "0.00"
            }

        historical_data = [
            {"timestamp": s.timestamp.isoformat(), "value": f"{Decimal(s.total_portfolio_value_usd):.2f}"}
            for s in portfolio_history
        ]

        # --- Calculate overall and 24h evolution ---
        evolution_total = Decimal("0")
        evolution_24h = Decimal("0")
        if len(portfolio_history) > 1:
            first_val = Decimal(portfolio_history[0].total_portfolio_value_usd)
            latest_val = Decimal(portfolio_history[-1].total_portfolio_value_usd)
            if first_val > 0:
                evolution_total = ((latest_val / first_val) - 1) * 100

            one_day_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
            snapshot_24h_ago = next((s for s in reversed(portfolio_history) if s.timestamp.replace(tzinfo=datetime.timezone.utc) <= one_day_ago), None)
            if snapshot_24h_ago:
                val_24h_ago = Decimal(snapshot_24h_ago.total_portfolio_value_usd)
                if val_24h_ago > 0:
                    evolution_24h = ((latest_val / val_24h_ago) - 1) * 100

        output = {
            "latest_snapshot": latest_snapshot_data,
            "dcom_status": dcom_data,
            "history": historical_data,
            "evolution_total": f"{evolution_total:.2f}",
            "evolution_24h": f"{evolution_24h:.2f}"
        }

        # Use default=str to handle Decimal serialization
        print(json.dumps(output, indent=4, default=str))

    except Exception as e:
        # Print errors to stderr to avoid polluting the stdout stream
        import traceback
        print(json.dumps({"error": str(e), "traceback": traceback.format_exc()}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    get_portfolio_data()