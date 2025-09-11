from decimal import Decimal

class StrategyGenerator:
    """
    Generates intelligent and adaptive parameter spaces for strategy optimization.
    """
    def __init__(self, config_manager):
        """
        Initializes the generator with a config manager to access base values.
        """
        self.cm = config_manager

    def generate_parameter_space(self, initial_balance: Decimal) -> dict:
        """
        Generates a dictionary of parameters and their ranges for optimization,
        tailored to the provided initial balance.

        The output format is compatible with the optimization script's config file.
        """
        # Define the parameter space
        parameter_space = {
            "base_usd_per_trade": {
                "section": "STRATEGY_RULES",
                "description": "Base order size in USD, adapted to initial balance.",
                "range": {
                    # Test order sizes from 1% to 5% of the initial balance, in 1% increments
                    "min": float(initial_balance * Decimal("0.01")),
                    "max": float(initial_balance * Decimal("0.05")),
                    "step": float(initial_balance * Decimal("0.01"))
                }
            },
            "buy_dip_percentage": {
                "section": "STRATEGY_RULES",
                "description": "The percentage drop from the high required to trigger a buy.",
                "range": {
                    "min": 0.01,
                    "max": 0.04,
                    "step": 0.01
                }
            },
            "sell_factor": {
                "section": "STRATEGY_RULES",
                "description": "Percentage of the position to sell when a signal is triggered.",
                "values": ["0.8", "0.9", "1.0"]
            },
            "trailing_stop_profit": {
                "section": "STRATEGY_RULES",
                "description": "Unrealized PnL percentage required to activate the trailing stop.",
                "range": {
                    "min": 0.05, # 5%
                    "max": 0.15, # 15%
                    "step": 0.05
                }
            }
        }

        # --- Final structure ---
        params = {
            "description": f"Auto-generated parameter space for a portfolio of ${initial_balance:,.2f}",
            "parameters": parameter_space,
            "settings": {
                "sort_by": "Sharpe Ratio",
                "ascending": False,
                "top_n_results": 10
            }
        }

        return params
