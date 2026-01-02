#!/bin/bash
set -e

echo "Starting GEMP Analytics Service..."

# Export environment variables for cron jobs
printenv | grep -E '^GEMP_|^MYSQL_' >> /etc/environment

# Start cron daemon in background
echo "Starting cron daemon..."
cron

# Wait for database to be ready
echo "Waiting for database connection..."
for i in {1..30}; do
    if mysqladmin ping -h"$GEMP_DB_HOST" -P"$GEMP_DB_PORT" -u"$GEMP_DB_USER" -p"$GEMP_DB_PASSWORD" --silent 2>/dev/null; then
        echo "Database is ready!"
        break
    fi
    echo "Waiting for database... ($i/30)"
    sleep 2
done

# Start the FastAPI server
echo "Starting API server..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
