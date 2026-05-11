# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1: builder
#   - installs the toolchain needed to compile cryptography / bcrypt wheels
#   - resolves and caches Python deps into a virtualenv
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
#   - minimal slim base, no compilers
#   - runs as non-root user `app` (uid 10001)
#   - only curl is added, for the healthcheck
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Drop the apt cache and only install the bare-minimum runtime deps.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy the resolved virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Create an unprivileged user / group.
RUN groupadd --system --gid 10001 app \
 && useradd  --system --uid 10001 --gid app --home /app --shell /sbin/nologin app

WORKDIR /app
COPY --chown=app:app ./app /app/app

# Make sure runtime dirs the app writes to are owned by `app`.
RUN mkdir -p /app/data && chown -R app:app /app

USER app:app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# tini = PID 1 -> proper signal forwarding to uvicorn.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
