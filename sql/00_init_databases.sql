-- 00_init_databases.sql
-- This runs once when the container is first created.

-- filings_analysis is created automatically by POSTGRES_DB, so we DO NOT recreate it here.

-- Create a separate test database
CREATE DATABASE filings_analysis_test;

-- Now connect to the dev database to do any per-db setup
\connect filings_analysis;

-- Optional: simple marker table or any initial setup
CREATE TABLE IF NOT EXISTS init_check (
    id SERIAL PRIMARY KEY,
    note TEXT DEFAULT 'initialized from docker sql folder',
    created_at TIMESTAMPTZ DEFAULT now()
);
