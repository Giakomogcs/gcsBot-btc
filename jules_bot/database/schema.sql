-- This file defines your entire table structure.
-- The current database is InfluxDB, which is schema-on-write. This SQL is for documentation and for potential future migration to SQL.
-- The schema is effectively defined by the points written in `database_manager.py`.

-- For InfluxDB, a new field `is_legacy_hold` will be added to the `trades` measurement.
-- It will be a boolean value.

-- If this were a SQL database, the table would look like this:
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL,
    -- ... other columns ...
    environment TEXT NOT NULL,
    is_legacy_hold BOOLEAN NOT NULL DEFAULT 0 -- SQLite uses 0 for False, 1 for True
);

-- To add this to an existing SQLite database, you would run:
-- ALTER TABLE trades ADD COLUMN is_legacy_hold BOOLEAN NOT NULL DEFAULT 0;
