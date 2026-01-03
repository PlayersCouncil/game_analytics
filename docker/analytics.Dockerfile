FROM python:3.11-slim

# Install cron and utilities
RUN apt-get update && apt-get install -y \
    cron \
    procps \
    default-mysql-client \
    curl \
    nano \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running the app
RUN useradd -m -s /bin/bash analytics

# Set working directory
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /app/logs /app/static

# Set ownership
RUN chown -R analytics:analytics /app

# Copy cron configuration
COPY docker/crontab /etc/cron.d/analytics-cron
RUN chmod 0644 /etc/cron.d/analytics-cron
RUN crontab /etc/cron.d/analytics-cron

# Create log files for cron
RUN touch /var/log/cron.log /app/logs/ingest.log /app/logs/precompute.log
RUN chown analytics:analytics /app/logs/*.log

# Expose API port
EXPOSE 8000

# Start script that runs both cron and the API
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
