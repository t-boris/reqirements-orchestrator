#!/bin/bash
# Initialize database with migrations

set -e

echo "Waiting for PostgreSQL..."
until pg_isready -h ${POSTGRES_HOST:-postgres} -p ${POSTGRES_PORT:-5432} -U ${POSTGRES_USER:-maro}; do
    echo "PostgreSQL is unavailable - sleeping"
    sleep 2
done

echo "PostgreSQL is ready - running migrations"
alembic upgrade head

echo "Database initialization complete"
