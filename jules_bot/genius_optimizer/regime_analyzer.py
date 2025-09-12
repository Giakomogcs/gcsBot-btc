import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.research.feature_engineering import add_all_features
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.utils.config_manager import config_manager

class RegimeAnalyzer:
    """
    Analyzes historical data to identify and segment it by market regime.
    This class encapsulates the logic for fetching data, calculating features,
    determining regimes, and splitting the data for the optimizer.
    """
    def __init__(self, db_manager: PostgresManager, days: int):
        self.db_manager = db_manager
        self.days = days
        self.full_data = None
        self.segmented_data = {}
        self.symbol = config_manager.get('APP', 'symbol')
        self.sa_model = SituationalAwareness()

    def load_data(self):
        """
        Loads the full historical dataset from the database.
        """
        logger.info(f"Loading historical data for the last {self.days} days...")
        start_date_str = f"-{self.days}d"
        end_date_str = "now()"
        self.full_data = self.db_manager.get_price_data(
            measurement=self.symbol,
            start_date=start_date_str,
            end_date=end_date_str
        )
        if self.full_data.empty:
            raise ValueError(f"No historical data found for symbol {self.symbol} in the last {self.days} days.")
        logger.info(f"Loaded {len(self.full_data)} rows of historical data.")

    def calculate_regimes(self):
        """
        Calculates features and market regimes for the entire dataset.
        This replicates the process used by the live bot and backtester.
        """
        logger.info("Calculating features for regime analysis...")
        # live_mode=False is important to ensure all features are calculated
        features_df = add_all_features(self.full_data, live_mode=False)

        logger.info("Calculating market regimes for the full dataset...")
        self.full_data = self.sa_model.transform(features_df).dropna()
        logger.info("Market regime calculation complete.")

    def segment_data(self) -> dict:
        """
        Splits the data into separate dataframes for each regime.

        Returns:
            A dictionary where keys are regime numbers (0, 1, 2, 3) and
            values are the corresponding pandas DataFrames.
        """
        logger.info("Segmenting data by market regime...")
        if 'market_regime' not in self.full_data.columns:
            raise ValueError("'market_regime' column not found after calculation.")

        for i in range(4): # Regimes 0, 1, 2, 3
            segment = self.full_data[self.full_data['market_regime'] == i]
            if not segment.empty:
                self.segmented_data[i] = segment
                logger.info(f"Regime {i} data segment created with {len(segment)} rows.")
            else:
                logger.warning(f"No data found for Regime {i}. This regime will be skipped in optimization.")

        return self.segmented_data

    def run(self) -> dict:
        """
        Executes the full analysis and segmentation process.
        """
        self.load_data()
        self.calculate_regimes()
        return self.segment_data()
