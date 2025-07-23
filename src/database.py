import os
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from src.logger import logger

from typing import List, Optional, Dict, Any

class Database:
    """A class to interact with a PostgreSQL database using SQLAlchemy."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        """
        Initializes the Database class.

        Args:
            db_url: The database URL. If not provided, it will be read from the DATABASE_URL environment variable.
        """
        if db_url is None:
            db_url = os.getenv("DATABASE_URL")
        if db_url is None:
            logger.error("DATABASE_URL environment variable not set.")
            raise ValueError("DATABASE_URL environment variable not set.")
        self.engine = create_engine(db_url)

    def connect(self) -> None:
        """Connects to the database."""
        try:
            self.engine.connect()
            logger.info("Database connection successful.")
        except SQLAlchemyError as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def disconnect(self) -> None:
        """Closes the database connection."""
        self.engine.dispose()
        logger.info("Database connection closed.")

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Executes a SQL query.

        Args:
            query: The SQL query to execute.
            params: The parameters to pass to the query.

        Returns:
            The result of the query execution.
        """
        with self.engine.connect() as connection:
            try:
                result = connection.execute(text(query), params or {})
                connection.commit()
                return result
            except SQLAlchemyError as e:
                logger.error(f"Query execution failed: {e}")
                raise

    def fetch_data(self, query: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Fetches data from the database.

        Args:
            query: The SQL query to execute.
            params: The parameters to pass to the query.

        Returns:
            A pandas DataFrame with the fetched data.
        """
        with self.engine.connect() as connection:
            try:
                return pd.read_sql(text(query), connection, params=params)
            except SQLAlchemyError as e:
                logger.error(f"Data fetching failed: {e}")
                raise

    def create_table(self, table_name: str, columns: List[str]) -> None:
        """
        Creates a table in the database.

        Args:
            table_name: The name of the table to create.
            columns: A list of strings with the column definitions.
        """
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns)});"
        self.execute_query(query)
        logger.info(f"Table '{table_name}' created successfully.")

    def insert_dataframe(self, df: pd.DataFrame, table_name: str, if_exists: str = 'append', index: bool = False) -> None:
        """
        Inserts a pandas DataFrame into a table.

        Args:
            df: The DataFrame to insert.
            table_name: The name of the table to insert the data into.
            if_exists: What to do if the table already exists.
            index: Whether to write the DataFrame's index as a column.
        """
        try:
            df.to_sql(table_name, self.engine, if_exists=if_exists, index=index)
            logger.info(f"Dataframe inserted into '{table_name}' successfully.")
        except SQLAlchemyError as e:
            logger.error(f"Dataframe insertion failed: {e}")
            raise
