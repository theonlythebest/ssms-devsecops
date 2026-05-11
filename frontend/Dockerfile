# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Hardened Nginx frontend.
#   - nginxinc/nginx-unprivileged: official Nginx image that runs as uid 101
#     and listens on 8080 instead of 80 (no need for CAP_NET_BIND_SERVICE).
#   - compose maps host :80 -> container :8080 (see docker-compose.yml).
# ---------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Non-root by default in this image (uid 101 / group nginx).
USER 101

# Drop the stock /usr/share/nginx/html and replace with our static assets.
COPY --chown=101:101 . /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
