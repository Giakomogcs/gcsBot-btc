import json
import sys
import os
import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.portfolio_manager import PortfolioManager

def get_portfolio_data():
    """
    Fetches the latest portfolio snapshot and historical data for the TUI.
    """
    try:
        db_config = config_manager.get_section('POSTGRES')
        portfolio_manager = PortfolioManager(db_config)

        latest_snapshot = portfolio_manager.get_latest_snapshot()
        all_snapshots = portfolio_manager.get_all_snapshots()

        # Prepare data for JSON serialization
        if latest_snapshot:
            latest_snapshot_data = {
                "id": latest_snapshot.id,
                "timestamp": latest_snapshot.timestamp.isoformat(),
                "total_portfolio_value_usd": latest_snapshot.total_portfolio_value_usd,
                "usd_balance": latest_snapshot.usd_balance,
                "open_positions_value_usd": latest_snapshot.open_positions_value_usd,
                "realized_pnl_usd": latest_snapshot.realized_pnl_usd,
                "btc_treasury_amount": latest_snapshot.btc_treasury_amount,
                "btc_treasury_value_usd": latest_snapshot.btc_treasury_value_usd,
                "evolution_percent_vs_previous": latest_snapshot.evolution_percent_vs_previous
            }
        else:
            latest_snapshot_data = None

        historical_data = [
            {
                "timestamp": s.timestamp.isoformat(),
                "value": s.total_portfolio_value_usd
            }
            for s in all_snapshots
        ]

        # Calculate overall and 24h evolution
        evolution_total = 0
        evolution_24h = 0
        if len(all_snapshots) > 1:
            first_snapshot_value = all_snapshots[0].total_portfolio_value_usd
            latest_snapshot_value = all_snapshots[-1].total_portfolio_value_usd
            if first_snapshot_value > 0:
                evolution_total = ((latest_snapshot_value / first_snapshot_value) - 1) * 100

            # Find snapshot from ~24 hours ago
            one_day_ago = datetime.datetime.utcnow() - datetime.timedelta(days=1)
            snapshot_24h_ago = None
            for s in reversed(all_snapshots):
                if s.timestamp <= one_day_ago:
                    snapshot_24h_ago = s
                    break

            if snapshot_24h_ago:
                if snapshot_24h_ago.total_portfolio_value_usd > 0:
                    evolution_24h = ((latest_snapshot_value / snapshot_24h_ago.total_portfolio_value_usd) - 1) * 100


        output = {
            "latest_snapshot": latest_snapshot_data,
            "history": historical_data,
            "evolution_total": evolution_total,
            "evolution_24h": evolution_24h
        }

        print(json.dumps(output, indent=4))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    get_portfolio_data()
