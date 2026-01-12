#!/bin/bash
set -e

# Create custom schema
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE SCHEMA IF NOT EXISTS ria;
    GRANT ALL ON SCHEMA ria TO $POSTGRES_USER;
EOSQL

echo "Schema 'ria' created successfully"
