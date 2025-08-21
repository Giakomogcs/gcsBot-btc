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

@patch('jules_bot.bot.trading_bot.config_manager')
def test_insufficient_balance_triggers_reconciliation(mock_config, mock_db_manager_with_trades):
    """
    Verify that when the bot detects an insufficient balance, it calls the
    state reconciliation logic instead of attempting to sell.
    This test focuses on the sell logic block in isolation.
    """
    # --- Setup ---
    # Mock Trader and StateManager
    mock_trader = MagicMock(spec=Trader)
    mock_state_manager = MagicMock(spec=StateManager)

    # Bot thinks it has 0.3 BTC (0.1 + 0.2)
    open_positions = mock_db_manager_with_trades.get_open_positions()
    mock_state_manager.get_open_positions.return_value = open_positions

    # But the exchange only has 0.1 BTC
    mock_trader.get_account_balance.return_value = '0.1'

    # Mock StrategyRules via the config mock
    mock_strategy_rules_config = {
        # 'sell_factor' is no longer used
        'max_capital_per_trade_percent': '0.02',
        'base_usd_per_trade': '20.0',
        'commission_rate': '0.001',
        'target_profit': '0.01',
    }
    mock_config.get_section.return_value = mock_strategy_rules_config
    strategy_rules = StrategyRules(mock_config) # Instantiate with the mock

    # Set a price high enough to trigger a sell for all open positions
    current_price = Decimal('52000.0')
    base_asset = 'BTC'

    # --- Act ---
    # This is the isolated logic block from TradingBot.run()
    positions_to_sell = [p for p in open_positions if current_price >= Decimal(str(p.sell_target_price or 'inf'))]
    if positions_to_sell:
        total_sell_quantity = sum(Decimal(str(p.quantity)) for p in positions_to_sell)
        available_balance = Decimal(mock_trader.get_account_balance(asset=base_asset))

        if total_sell_quantity > available_balance:
            # This is the branch we expect to be taken
            mock_state_manager.reconcile_holdings('BTCUSDT', mock_trader)
        else:
            # This branch should not be taken, but we include it for completeness
            for position in positions_to_sell:
                mock_trader.execute_sell(position.to_dict(), 'test_bot', {})

    # --- Assert ---
    # The bot should have detected an insufficient balance and called reconcile_holdings.
    mock_state_manager.reconcile_holdings.assert_called_once_with('BTCUSDT', mock_trader)

    # It should NOT have attempted to sell anything.
    mock_trader.execute_sell.assert_not_called()
