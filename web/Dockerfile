FROM python:3.12-slim

WORKDIR /app

# System deps for bleak (BlueZ) — not strictly needed for the web frontend
# but kept so the core library can be imported
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        cron \
        openssl \
    && rm -rf /var/lib/apt/lists/*

# Install acme.sh
RUN curl https://get.acme.sh | sh -s -- --install-online 2>/dev/null || true

COPY web/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY core /app/core
COPY web  /app/web

# SSL placeholder directory
RUN mkdir -p /root/Water/ssl

COPY web/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
