from binance.client import Client
from jules_bot.database.portfolio_manager import PortfolioManager

class TransactionSyncService:
    def __init__(self, portfolio_manager: PortfolioManager, client: Client):
        self.portfolio_manager = portfolio_manager
        self.client = client

    def sync_transactions(self):
        self._sync_deposits()
        self._sync_withdrawals()

    def _sync_deposits(self):
        deposits = self.client.get_deposit_history()
        for deposit in deposits:
            if deposit["status"] == 1:  # 1 means completed
                if not self.portfolio_manager.get_financial_movement_by_transaction_id(deposit["txId"]):
                    self.portfolio_manager.create_financial_movement(
                        transaction_id=deposit["txId"],
                        movement_type="DEPOSIT",
                        amount_usd=float(deposit["amount"]),
                        notes=f"Deposit of {deposit['amount']} {deposit['coin']}"
                    )

    def _sync_withdrawals(self):
        withdrawals = self.client.get_withdraw_history()
        for withdrawal in withdrawals:
            if withdrawal["status"] == 6:  # 6 means completed
                if not self.portfolio_manager.get_financial_movement_by_transaction_id(withdrawal["txId"]):
                    self.portfolio_manager.create_financial_movement(
                        transaction_id=withdrawal["txId"],
                        movement_type="WITHDRAWAL",
                        amount_usd=float(withdrawal["amount"]),
                        notes=f"Withdrawal of {withdrawal['amount']} {withdrawal['coin']}"
                    )
