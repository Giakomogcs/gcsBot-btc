-- Create schemas for different environments
CREATE SCHEMA IF NOT EXISTS live;
CREATE SCHEMA IF NOT EXISTS backtest;
CREATE SCHEMA IF NOT EXISTS paper;

-- Grant usage on schemas to the user
GRANT USAGE ON SCHEMA live TO gcs_user;
GRANT USAGE ON SCHEMA backtest TO gcs_user;
GRANT USAGE ON SCHEMA paper TO gcs_user;

-- Set the search path for the user
ALTER ROLE gcs_user SET search_path = live, backtest, paper, public;
