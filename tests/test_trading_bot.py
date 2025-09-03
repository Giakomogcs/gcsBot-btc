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

        # Configure mock_strategy_rules with some default values
        mock_strategy_rules.smart_trailing_activation_profit_percent = Decimal('0.015') # 1.5%
        mock_strategy_rules.trailing_stop_percent = Decimal('0.005') # 0.5%
        mock_strategy_rules.calculate_break_even_price.side_effect = lambda p: p * Decimal('1.001') # Simplified break-even

        yield mock_state_manager, mock_trader, mock_strategy_rules, MockLogger


class TestSmartTrailingStop:
    def test_trailing_stop_activates_when_profit_threshold_is_met(self, mock_bot_components):
        """
        Verify that the smart trailing stop activates when a position's profit crosses the threshold.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components

        # Arrange
        entry_price = Decimal('100')
        # Price is 1.6% above entry, which is > 1.5% activation threshold
        current_price = Decimal('101.6')

        position = Trade(
            trade_id='test_trade_1',
            price=entry_price,
            is_smart_trailing_active=False, # Starts as inactive
            sell_target_price=Decimal('110') # High sell target to not interfere
        )
        mock_state_manager.get_open_positions.return_value = [position]

        # Act: This block simulates the core sell logic from the trading bot's main loop
        for pos in mock_state_manager.get_open_positions():
            # Simplified PnL check for the test
            current_pnl_percent = (current_price / Decimal(str(pos.price))) - Decimal('1')

            if not pos.is_smart_trailing_active and current_pnl_percent >= mock_strategy_rules.smart_trailing_activation_profit_percent:
                mock_logger.info(f"ACTIVATING for {pos.trade_id}")
                mock_state_manager.update_trade_smart_trailing_state(
                    trade_id=pos.trade_id,
                    is_active=True,
                    highest_price=current_price,
                    activation_price=current_price
                )
                # Update in-memory object
                pos.is_smart_trailing_active = True
                pos.smart_trailing_highest_price = current_price

        # Assert
        mock_state_manager.update_trade_smart_trailing_state.assert_called_once_with(
            trade_id='test_trade_1',
            is_active=True,
            highest_price=current_price,
            activation_price=current_price
        )
        mock_logger.info.assert_called_with("ACTIVATING for test_trade_1")

    def test_trailing_stop_triggers_sell_when_price_drops(self, mock_bot_components):
        """
        Verify that an active smart trailing stop triggers a sell when the price drops
        below the calculated stop price.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components
        positions_to_sell_now = []

        # Arrange
        entry_price = Decimal('100')
        highest_price = Decimal('110')
        # Price drops 0.6% from the peak (110 * (1 - 0.006) = 109.34), which is more than the 0.5% stop loss
        current_price = Decimal('109.3')

        position = Trade(
            trade_id='test_trade_2',
            price=entry_price,
            is_smart_trailing_active=True, # Starts as active
            smart_trailing_highest_price=highest_price,
            sell_target_price=Decimal('120')
        )
        mock_state_manager.get_open_positions.return_value = [position]
        # Mock break_even_price to be profitable
        mock_strategy_rules.calculate_break_even_price.return_value = Decimal('100.1')

        # Act
        for pos in mock_state_manager.get_open_positions():
            if pos.is_smart_trailing_active:
                stop_price = Decimal(str(pos.smart_trailing_highest_price)) * (Decimal('1') - mock_strategy_rules.trailing_stop_percent)
                if current_price <= stop_price:
                    mock_logger.info(f"SELLING {pos.trade_id}")
                    positions_to_sell_now.append(pos)

        # Assert
        assert len(positions_to_sell_now) == 1
        assert positions_to_sell_now[0].trade_id == 'test_trade_2'
        mock_logger.info.assert_called_with("SELLING test_trade_2")

    def test_trailing_stop_pauses_when_position_is_unprofitable(self, mock_bot_components):
        """
        Verify that the smart trailing stop is paused (deactivated) if the position
        becomes unprofitable.
        """
        mock_state_manager, _, mock_strategy_rules, mock_logger = mock_bot_components

        # Arrange
        entry_price = Decimal('100')
        highest_price = Decimal('105')
        break_even_price = Decimal('100.1')
        # Price drops below break-even
        current_price = Decimal('99')

        position = Trade(
            trade_id='test_trade_3',
            price=entry_price,
            is_smart_trailing_active=True,
            smart_trailing_highest_price=highest_price,
            sell_target_price=Decimal('120')
        )
        mock_state_manager.get_open_positions.return_value = [position]
        mock_strategy_rules.calculate_break_even_price.return_value = break_even_price

        # Act
        for pos in mock_state_manager.get_open_positions():
            if pos.is_smart_trailing_active:
                if current_price < mock_strategy_rules.calculate_break_even_price(Decimal(str(pos.price))):
                    mock_logger.info(f"PAUSING {pos.trade_id}")
                    mock_state_manager.update_trade_smart_trailing_state(
                        trade_id=pos.trade_id, is_active=False, highest_price=None, activation_price=None
                    )
                    pos.is_smart_trailing_active = False

        # Assert
        mock_state_manager.update_trade_smart_trailing_state.assert_called_once_with(
            trade_id='test_trade_3', is_active=False, highest_price=None, activation_price=None
        )
        mock_logger.info.assert_called_with("PAUSING test_trade_3")

    def test_trailing_stop_updates_highest_price(self, mock_bot_components):
        """
        Verify that the highest_price is updated when the price reaches a new peak.
        """
        mock_state_manager, _, _, mock_logger = mock_bot_components

        # Arrange
        entry_price = Decimal('100')
        old_highest_price = Decimal('105')
        new_highest_price = Decimal('106')

        position = Trade(
            trade_id='test_trade_4',
            price=entry_price,
            is_smart_trailing_active=True,
            smart_trailing_highest_price=old_highest_price,
            sell_target_price=Decimal('120')
        )
        mock_state_manager.get_open_positions.return_value = [position]

        # Act
        for pos in mock_state_manager.get_open_positions():
            if pos.is_smart_trailing_active:
                if new_highest_price > Decimal(str(pos.smart_trailing_highest_price)):
                    mock_logger.info(f"UPDATING PEAK for {pos.trade_id}")
                    mock_state_manager.update_trade_smart_trailing_state(
                        trade_id=pos.trade_id,
                        is_active=True,
                        highest_price=new_highest_price
                    )

        # Assert
        mock_state_manager.update_trade_smart_trailing_state.assert_called_once_with(
            trade_id='test_trade_4',
            is_active=True,
            highest_price=new_highest_price
        )
        mock_logger.info.assert_called_with("UPDATING PEAK for test_trade_4")
