#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until python -c "import psycopg2, os; psycopg2.connect(os.environ['DATABASE_URL'])" 2>/dev/null; do
  sleep 1
done

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting FastAPI..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
