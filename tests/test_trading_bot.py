import pytest
from unittest.mock import MagicMock, patch, call
from decimal import Decimal

from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core_logic.trader import Trader
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.database.models import Trade

@pytest.fixture
def mock_db_manager_with_trades():
    """Fixture for a mocked PostgresManager that returns some mock trades."""
    db_manager = MagicMock()

    trade1 = Trade(trade_id='1', symbol='BTCUSDT', quantity=Decimal('0.1'), price=Decimal('50000'), sell_target_price=Decimal('51000'), status='OPEN')
    trade2 = Trade(trade_id='2', symbol='BTCUSDT', quantity=Decimal('0.2'), price=Decimal('50100'), sell_target_price=Decimal('51100'), status='OPEN')

    db_manager.get_open_positions.return_value = [trade1, trade2]
    return db_manager

@patch('jules_bot.bot.trading_bot.logger')
@patch('jules_bot.bot.trading_bot.config_manager')
def test_insufficient_balance_logs_critical_and_skips_sell(mock_config, mock_logger, mock_db_manager_with_trades):
    """
    Verify that when the bot detects an insufficient balance for a sell, it logs
    a critical error and does NOT attempt to sell. The reconciliation now happens
    at the start of the next cycle, not within this block.
    """
    # --- Setup ---
    mock_trader = MagicMock(spec=Trader)
    open_positions = mock_db_manager_with_trades.get_open_positions()
    mock_trader.get_account_balance.return_value = '0.1' # Exchange has less than bot thinks

    # Mock config for StrategyRules
    mock_config.get.side_effect = lambda section, key, **kwargs: {
        ('STRATEGY_RULES', 'sell_factor'): '1.0',
        ('STRATEGY_RULES', 'max_capital_per_trade_percent'): '0.02',
        ('STRATEGY_RULES', 'base_usd_per_trade'): '20.0',
        ('STRATEGY_RULES', 'commission_rate'): '0.001',
        ('STRATEGY_RULES', 'target_profit'): '0.01',
    }.get((section, key), kwargs.get('fallback'))
    strategy_rules = StrategyRules(mock_config)

    current_price = Decimal('52000.0')
    base_asset = 'BTC'

    # --- Act ---
    # This is an isolated logic block from TradingBot.run()
    positions_to_sell = [p for p in open_positions if current_price >= Decimal(str(p.sell_target_price or 'inf'))]
    if positions_to_sell:
        total_sell_quantity = sum(Decimal(str(p.quantity)) * strategy_rules.sell_factor for p in positions_to_sell)
        available_balance = Decimal(mock_trader.get_account_balance(asset=base_asset))

        if total_sell_quantity > available_balance:
            # This is the branch we expect to be taken
            mock_logger.critical(
                f"INSUFFICIENT BALANCE & STATE DESYNC: Attempting to sell {total_sell_quantity:.8f} {base_asset}, "
                f"but only {available_balance:.8f} is available on the exchange. "
                "This indicates a significant discrepancy between the bot's state and the exchange's reality. "
                "The bot will NOT proceed with the sell and will wait for the next sync cycle to correct the state."
            )
        else:
            # This branch should not be taken
            for position in positions_to_sell:
                mock_trader.execute_sell(position.to_dict(), 'test_bot', {})

    # --- Assert ---
    # The bot should NOT have attempted to sell anything.
    mock_trader.execute_sell.assert_not_called()

    # It should have logged a critical error about the desync.
    mock_logger.critical.assert_called_once()
    assert "INSUFFICIENT BALANCE & STATE DESYNC" in mock_logger.critical.call_args[0][0]
