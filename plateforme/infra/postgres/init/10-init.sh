#!/bin/sh
# Runs once, on the first start of an empty data volume (docker-entrypoint-initdb.d).
# Enables pgvector in the CERVEAU database and creates the Langfuse role and database.
# The password is read with \getenv so that it never appears on a command line.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv langfuse_password LANGFUSE_DB_PASSWORD
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE langfuse LOGIN PASSWORD :'langfuse_password';
CREATE DATABASE langfuse OWNER langfuse;
SQL
