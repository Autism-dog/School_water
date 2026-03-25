#!/usr/bin/env bash
# entrypoint.sh — start cron (for acme.sh renewal) + uvicorn
set -e

# Start cron so acme.sh automatic renewal works
cron

# Start the FastAPI application
exec uvicorn web.app:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 2
