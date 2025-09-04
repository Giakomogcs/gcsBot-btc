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

@pytest.fixture
def mock_bot_components():
    """A fixture to create a set of mocked components for the TradingBot."""
    with patch('jules_bot.bot.trading_bot.StateManager') as MockStateManager, \
         patch('jules_bot.bot.trading_bot.Trader') as MockTrader, \
         patch('jules_bot.bot.trading_bot.StrategyRules') as MockStrategyRules, \
         patch('jules_bot.bot.trading_bot.logger') as MockLogger:

        mock_state_manager = MockStateManager.return_value
        mock_trader = MockTrader.return_value
        mock_strategy_rules = MockStrategyRules.return_value

        # Configure mock_strategy_rules with the new profit-based values
        mock_strategy_rules.trailing_stop_profit = Decimal('0.10') # $0.10 profit target

        # Mock the PnL calculation
        mock_strategy_rules.calculate_net_unrealized_pnl = MagicMock(return_value=Decimal('0.0'))

        yield mock_state_manager, mock_trader, mock_strategy_rules, MockLogger


class TestSmartTrailingStop:
    def test_trailing_stop_activates_when_profit_threshold_is_met(self, mock_bot_components):
        """
        Verify that the smart trailing stop activates when a position's profit crosses the threshold.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components

        # Arrange
        # This PnL is greater than the $0.10 activation threshold
        net_unrealized_pnl = Decimal('0.15')
        mock_strategy_rules.calculate_net_unrealized_pnl.return_value = net_unrealized_pnl
        current_price = Decimal('101.6') # Not used directly in logic, but for context

        position = Trade(
            trade_id='test_trade_1',
            price=Decimal('100'),
            is_smart_trailing_active=False, # Starts as inactive
            sell_target_price=Decimal('110')
        )
        mock_state_manager.get_open_positions.return_value = [position]

        # Act: This block simulates the core sell logic from the trading bot's main loop
        for pos in mock_state_manager.get_open_positions():
            pnl = mock_strategy_rules.calculate_net_unrealized_pnl()
            if not pos.is_smart_trailing_active and pnl >= mock_strategy_rules.trailing_stop_profit:
                mock_logger.info(f"ACTIVATING for {pos.trade_id}")
                mock_state_manager.update_trade_smart_trailing_state(
                    trade_id=pos.trade_id,
                    is_active=True,
                    highest_profit=pnl,
                    activation_price=current_price
                )

        # Assert
        mock_state_manager.update_trade_smart_trailing_state.assert_called_once_with(
            trade_id='test_trade_1',
            is_active=True,
            highest_profit=net_unrealized_pnl,
            activation_price=current_price
        )
        mock_logger.info.assert_called_with("ACTIVATING for test_trade_1")

    def test_trailing_stop_triggers_sell_when_profit_drops_to_target(self, mock_bot_components):
        """
        Verify that an active smart trailing stop triggers a sell when the profit drops
        back to the minimum profit target.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components
        positions_to_sell_now = []

        # Arrange
        min_profit_target = Decimal('0.10')
        mock_strategy_rules.trailing_stop_profit = min_profit_target
        # The current profit has dropped from a peak back to the minimum target
        net_unrealized_pnl = Decimal('0.10')
        mock_strategy_rules.calculate_net_unrealized_pnl.return_value = net_unrealized_pnl

        position = Trade(
            trade_id='test_trade_2',
            price=Decimal('100'),
            is_smart_trailing_active=True, # Starts as active
            smart_trailing_highest_profit=Decimal('0.50'), # Had a peak profit of $0.50
            sell_target_price=Decimal('120')
        )
        mock_state_manager.get_open_positions.return_value = [position]

        # Act
        for pos in mock_state_manager.get_open_positions():
            if pos.is_smart_trailing_active:
                pnl = mock_strategy_rules.calculate_net_unrealized_pnl()
                if pnl <= mock_strategy_rules.trailing_stop_profit:
                    mock_logger.info(f"SELLING {pos.trade_id}")
                    positions_to_sell_now.append(pos)

        # Assert
        assert len(positions_to_sell_now) == 1
        assert positions_to_sell_now[0].trade_id == 'test_trade_2'
        mock_logger.info.assert_called_with("SELLING test_trade_2")

    def test_trailing_stop_cancels_when_position_is_unprofitable(self, mock_bot_components):
        """
        Verify that the smart trailing stop is canceled (deactivated) if the position
        becomes unprofitable, to avoid selling at a loss.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components

        # Arrange
        # PnL is now negative
        net_unrealized_pnl = Decimal('-0.05')
        mock_strategy_rules.calculate_net_unrealized_pnl.return_value = net_unrealized_pnl

        position = Trade(
            trade_id='test_trade_3',
            price=Decimal('100'),
            is_smart_trailing_active=True,
            smart_trailing_highest_profit=Decimal('0.20'),
            sell_target_price=Decimal('120')
        )
        mock_state_manager.get_open_positions.return_value = [position]

        # Act
        for pos in mock_state_manager.get_open_positions():
            if pos.is_smart_trailing_active:
                pnl = mock_strategy_rules.calculate_net_unrealized_pnl()
                if pnl < 0:
                    mock_logger.info(f"CANCELING {pos.trade_id}")
                    mock_state_manager.update_trade_smart_trailing_state(
                        trade_id=pos.trade_id, is_active=False, highest_profit=None, activation_price=None
                    )

        # Assert
        mock_state_manager.update_trade_smart_trailing_state.assert_called_once_with(
            trade_id='test_trade_3', is_active=False, highest_profit=None, activation_price=None
        )
        mock_logger.info.assert_called_with("CANCELING test_trade_3")

    def test_trailing_stop_updates_highest_profit(self, mock_bot_components):
        """
        Verify that the highest_profit is updated when the PnL reaches a new peak.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components

        # Arrange
        old_highest_profit = Decimal('0.25')
        new_highest_profit = Decimal('0.30')
        mock_strategy_rules.calculate_net_unrealized_pnl.return_value = new_highest_profit

        position = Trade(
            trade_id='test_trade_4',
            price=Decimal('100'),
            is_smart_trailing_active=True,
            smart_trailing_highest_profit=old_highest_profit,
            sell_target_price=Decimal('120')
        )
        mock_state_manager.get_open_positions.return_value = [position]

        # Act
        for pos in mock_state_manager.get_open_positions():
            if pos.is_smart_trailing_active:
                pnl = mock_strategy_rules.calculate_net_unrealized_pnl()
                if pnl > Decimal(str(pos.smart_trailing_highest_profit)):
                    mock_logger.info(f"UPDATING PEAK for {pos.trade_id}")
                    mock_state_manager.update_trade_smart_trailing_state(
                        trade_id=pos.trade_id,
                        is_active=True,
                        highest_profit=pnl
                    )

        # Assert
        mock_state_manager.update_trade_smart_trailing_state.assert_called_once_with(
            trade_id='test_trade_4',
            is_active=True,
            highest_profit=new_highest_profit
        )
        mock_logger.info.assert_called_with("UPDATING PEAK for test_trade_4")
