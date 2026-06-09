
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER 101

COPY --chown=101:101 . /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
