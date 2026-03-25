#!/usr/bin/env bash
# ssl_renew.sh — Issue / renew a Let's Encrypt certificate and reload nginx.
#
# Usage:
#   DOMAIN=example.com DOMAIN_ALT=www.example.com ./ssl_renew.sh
#
# Environment variables:
#   DOMAIN      Primary domain (required)
#   DOMAIN_ALT  Additional domain (optional)
#
# The certificate is installed to:
#   /root/Water/ssl/privkey.key
#   /root/Water/ssl/fullchain.pem
#
# After installation nginx is sent a SIGHUP so it hot-reloads the new cert
# without dropping any active connections.

set -euo pipefail

DOMAIN="${DOMAIN:?DOMAIN env variable is required}"
SSL_DIR="/root/Water/ssl"
ACME="${HOME}/.acme.sh/acme.sh"

mkdir -p "$SSL_DIR"

# Build -d flags
DOMAIN_FLAGS="-d ${DOMAIN}"
if [[ -n "${DOMAIN_ALT:-}" ]]; then
    DOMAIN_FLAGS="${DOMAIN_FLAGS} -d ${DOMAIN_ALT}"
fi

echo "[ssl_renew] Issuing certificate for ${DOMAIN_FLAGS}..."
# shellcheck disable=SC2086
"$ACME" --issue \
    --server letsencrypt \
    --standalone \
    ${DOMAIN_FLAGS} \
    --certificate-profile shortlived \
    --force || true   # '--force' re-issues even if not yet expired

echo "[ssl_renew] Installing certificate..."
# shellcheck disable=SC2086
"$ACME" --install-cert \
    -d "${DOMAIN}" \
    --key-file      "${SSL_DIR}/privkey.key" \
    --fullchain-file "${SSL_DIR}/fullchain.pem" \
    --reloadcmd "docker exec school-water-nginx nginx -s reload 2>/dev/null || true"

echo "[ssl_renew] Done. Certificate is at ${SSL_DIR}/"

# Also send nginx a reload signal directly in case the --reloadcmd path fails
# (e.g. if this script runs inside the same container)
nginx -s reload 2>/dev/null || true
