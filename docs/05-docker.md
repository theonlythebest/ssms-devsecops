# 5. Docker + Docker Compose deep-dive

## 5.1 Containers, images, and why they matter

A **container** is a process running on a Linux host, with its own filesystem
view, its own network stack, and limited capabilities — all enforced by Linux
kernel features (`cgroups`, `namespaces`, `capabilities`, `seccomp`). It is
**not** a virtual machine; it shares the host kernel. Spinning one up takes
milliseconds.

An **image** is a read-only stack of filesystem layers that a container is
instantiated from. Images are versioned, immutable, and addressable
(`ssms/backend:latest` or `python:3.12-slim@sha256:...`). They're the units
you ship from CI to production.

Why containers won DevOps:

- **Reproducibility**: "works on my machine" goes away because *everyone*
  uses the same image bytes.
- **Isolation**: a vulnerable Python lib in your API can't write to MariaDB's
  files because the API and the DB are in different containers.
- **Density**: dozens of containers fit on one VM that would otherwise host
  one app.
- **Imperatively immutable**: you don't `ssh + apt upgrade` a container. You
  rebuild the image, push, replace the container. This makes drift impossible.

## 5.2 What Docker Compose does

A single container = `docker run`. A whole stack of containers (frontend +
backend + DB + Prometheus + Grafana) talking to each other = `docker compose`.

Compose reads `docker-compose.yml`, which declares:

- One **service** per container with its image, env vars, ports, volumes.
- A shared **network** so containers find each other by service name.
- Named **volumes** for persistent data.
- Dependencies (`depends_on`), so containers boot in the right order.
- Health-checks that make `depends_on: service_healthy` meaningful.

It is opinionated, declarative, and idempotent in the same way Ansible is —
`docker compose up -d` brings the stack to the declared state, regardless of
the current state.

## 5.3 The two Dockerfiles

### 5.3.1 `backend/Dockerfile` — multi-stage, non-root, signal-safe

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 VIRTUAL_ENV=/opt/venv
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc libffi-dev && rm -rf /var/lib/apt/lists/*
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* && apt-get clean
COPY --from=builder /opt/venv /opt/venv
RUN groupadd --system --gid 10001 app && \
    useradd  --system --uid 10001 --gid app --home /app --shell /sbin/nologin app
WORKDIR /app
COPY --chown=app:app ./app /app/app
RUN mkdir -p /app/data && chown -R app:app /app
USER app:app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
    CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

What each line accomplishes:

- **Multi-stage**: the `builder` stage installs gcc to compile cryptography
  and bcrypt wheels, then we copy only the resolved virtualenv into the
  `runtime` stage. The shipped image has no compilers, smaller surface area,
  smaller size, smaller Trivy report.
- `PYTHONDONTWRITEBYTECODE=1` — no `.pyc` files in the image. Slightly faster
  start, no leftover compiled bytecode confusion across rebuilds.
- `PIP_NO_CACHE_DIR=1` — pip never persists a download cache. Even smaller image.
- `--no-install-recommends` — apt only installs explicitly-named packages,
  not "recommended" extras. Drops the image by a few MB and reduces CVE count.
- `useradd --system --uid 10001 ... --shell /sbin/nologin app` — creates a
  non-root user. uid 10001 (not the conventional 1000) signals "system
  account, no human-style shell access".
- `USER app:app` — every command **after** this line runs as the `app` user.
  If uvicorn is exploited via remote code execution, the attacker lands as
  uid 10001 in a container with no capabilities, no SUID binaries, and no
  package manager — a hard playground.
- `HEALTHCHECK` — Docker periodically pings `/health`. If it fails enough,
  the container is marked `unhealthy` and `depends_on: service_healthy`
  refuses to start anything that depends on it. This is what makes the boot
  ordering deterministic.
- `ENTRYPOINT ["/usr/bin/tini", "--"]` — `tini` is a tiny init wrapper that
  becomes PID 1 inside the container. PID 1 has special responsibilities in
  Linux (forwarding signals, reaping zombies). Python is not designed to be
  PID 1; if Compose sends SIGTERM during shutdown, raw Python may take 30
  seconds to die. Tini forwards the signal immediately to uvicorn, which
  cleanly stops.

### 5.3.2 `frontend/Dockerfile`

```dockerfile
FROM nginxinc/nginx-unprivileged:1.27-alpine
USER 101
COPY --chown=101:101 . /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
```

- We use **`nginx-unprivileged`**, the official Nginx variant configured to
  run as uid 101 and listen on port 8080 (the standard `nginx` image needs
  root to bind to port 80).
- All static files are owned by uid 101.
- The compose file maps host port 80 to container port 8080.

### 5.3.3 Why not Alpine for the backend?

We could shrink further by switching to `python:3.12-alpine`. We chose
`python:3.12-slim` (Debian-based) because:

- `cryptography` and `bcrypt` ship pre-built wheels for `manylinux` (Debian
  glibc) but not for `musl` (Alpine). On Alpine they'd have to compile from
  source on every build, adding minutes to CI.
- Debian's CVE patch cadence is well-understood. Alpine's musl libc trips
  rare-but-real bugs in some Python C extensions.

This is a deliberate trade-off: slightly larger image, much smoother build.

## 5.4 docker-compose.yml — service by service

```yaml
services:
  mariadb:
    image: mariadb:11
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-rootpassword}
      MYSQL_DATABASE:      ${MYSQL_DATABASE:-ssms}
      MYSQL_USER:          ${MYSQL_USER:-ssmsuser}
      MYSQL_PASSWORD:      ${MYSQL_PASSWORD:-strongpassword}
    volumes: [ "mariadb_data:/var/lib/mysql" ]
    ports:   [ "3306:3306" ]
    healthcheck:
      test: ["CMD","mariadb-admin","ping","-h","localhost","-uroot","-p${MYSQL_ROOT_PASSWORD:-rootpassword}"]
      interval: 5s
      retries: 20
      start_period: 20s
    security_opt: [ "no-new-privileges:true" ]
    networks: [ ssms_net ]
```

- `${VAR:-default}` is shell-style variable substitution. `compose` reads
  the project's `.env` file at parse time. If `MYSQL_PASSWORD` is missing,
  the literal `strongpassword` is used (useful for local dev only).
- `volumes: mariadb_data:/var/lib/mysql` mounts a **named volume** at the
  data dir, so DB content survives container deletion. Use `docker compose
  down -v` to also wipe the volume.
- `ports: ["3306:3306"]` publishes the DB on the host. The UFW firewall +
  AWS security group still close it to the public internet (defense in
  depth — the docker port publication alone would be too permissive).
- `healthcheck` uses `mariadb-admin ping` with credentials. Without the
  `-uroot -p...` flag, the new MariaDB 11 image considers the ping
  unauthenticated and may fail it.
- `no-new-privileges:true` — even if a process inside the container calls
  `setuid` on a SUID binary, the kernel refuses to grant elevated privileges.

```yaml
  backend:
    build: ./backend
    image: ssms/backend:latest
    depends_on: { mariadb: { condition: service_healthy } }
    environment:
      DATABASE_URL:        ${DATABASE_URL:-...}
      JWT_SECRET:          ${JWT_SECRET:-...}
      ...
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:8000/health || exit 1"]
    security_opt: [ "no-new-privileges:true" ]
    cap_drop: [ ALL ]
    networks: [ ssms_net ]
```

- `depends_on: condition: service_healthy` — Compose won't start the backend
  until MariaDB's healthcheck reports green. Combined with the backend's own
  retry loop, boot is fully deterministic.
- `cap_drop: [ ALL ]` — drops every Linux capability granted to the container.
  Backend doesn't need `CAP_NET_RAW` (no raw sockets), doesn't need
  `CAP_SYS_ADMIN` (no mount), doesn't need anything. The capability set
  becomes empty.
- We did **not** add `read_only: true` to the backend's filesystem because
  SQLAlchemy can transiently want to write log/cache files. Could be tightened
  with `tmpfs:` mounts as a follow-up.

```yaml
  frontend:
    build: ./frontend
    image: ssms/frontend:latest
    ports: [ "80:8080" ]                 # host 80 -> container 8080
    cap_drop: [ ALL ]
    security_opt: [ "no-new-privileges:true" ]

  prometheus:
    image: prom/prometheus
    ports: [ "9090:9090" ]
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    security_opt: [ "no-new-privileges:true" ]

  grafana:
    image: grafana/grafana
    environment:
      GF_SECURITY_ADMIN_USER:     ${GF_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GF_ADMIN_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP:     "false"
    ports: [ "3000:3000" ]
    volumes: [ "grafana_data:/var/lib/grafana" ]
    security_opt: [ "no-new-privileges:true" ]

volumes:
  mariadb_data:
  prometheus_data:
  grafana_data:

networks:
  ssms_net: { driver: bridge }
```

## 5.5 Container networking explained

When Compose starts, it creates a **bridge network** called `ssms_net`. All
five containers attach to it. Linux's userspace DNS resolver inside each
container is wired so that **service names resolve to container IPs**:

```
backend $ nslookup mariadb
mariadb has address 172.18.0.3
backend $ nslookup prometheus
prometheus has address 172.18.0.4
```

That's why the backend's `DATABASE_URL` is
`mysql+pymysql://ssmsuser:...@mariadb:3306/ssms?charset=utf8mb4` — `mariadb`
is a DNS name *inside* the docker network, not a hostname on the public
internet. Likewise, Prometheus scrapes `http://backend:8000/metrics`.

The bridge network is **isolated from the host network**. Nothing on the
host can talk to `mariadb:3306` unless that port is also published. This
is the runtime backbone of *defense in depth*: even if the backend is
compromised, the attacker is still trapped on `ssms_net` and can't reach,
say, your other VMs.

## 5.6 Healthchecks explained

Every service has a healthcheck. The kernel pings the command listed in
`test:` at the given `interval`. After `retries` consecutive failures, the
container goes `unhealthy`. Any `depends_on: service_healthy` blocks
dependent boot.

Why this matters:

- Boot order. Without it, the backend might attempt to connect to MariaDB
  before MariaDB has finished its first-init schema creation, and crash-loop.
- Liveness. Compose can `restart: unless-stopped` an unhealthy container.
- Visibility. `docker ps` shows `Up 2 minutes (healthy)`.

## 5.7 Container hardening — full summary

| Control                          | Where                  | Why                                          |
|----------------------------------|------------------------|----------------------------------------------|
| Non-root user (`app`, `nginx`)   | Dockerfile             | RCE in app -> non-root inside container       |
| Multi-stage build                | backend Dockerfile     | No compilers / dev libs in shipped image     |
| Slim base images                 | both Dockerfiles       | Fewer libraries -> fewer CVEs                |
| `no-new-privileges:true`         | compose                | Blocks setuid escalation                     |
| `cap_drop: [ALL]`                | compose                | Empty capability set                         |
| `HEALTHCHECK`                    | Dockerfile + compose   | Deterministic boot ordering, restart policy  |
| Named volumes (not bind mounts)  | compose                | Data outlives container, but isolated path   |
| `tini` as PID 1                  | backend Dockerfile     | Proper signal handling on `docker stop`      |
| Secrets via `.env` (gitignored)  | compose                | No secrets in source                         |
| `:ro` mount for prometheus.yml   | compose                | Container can't modify its own config        |

Each by itself is mostly cosmetic. Stacked, they raise the cost of an
exploit by an order of magnitude.

## 5.8 The build → run pipeline

```
$ docker compose build                # CI does this with --no-cache
  ├─ reads backend/Dockerfile
  ├─ stage 1: builder       (compile wheels into /opt/venv)
  └─ stage 2: runtime       (copy /opt/venv, set up app user, USER app)
  -> image: ssms/backend:latest    (sha256:abc...)

$ docker compose up -d --wait
  ├─ creates network ssms_net
  ├─ creates volumes mariadb_data, prometheus_data, grafana_data
  ├─ starts mariadb           (wait for healthcheck green)
  ├─ starts backend           (wait for healthcheck green)
  ├─ starts frontend, prometheus
  └─ starts grafana
  -> exits 0 when every service is "healthy"
```

The `--wait` flag is what turns Compose from a "fire and forget" command
into a deterministic deployment step. Without it, a transient slow boot
would leave Ansible thinking the stack is up while it's still initializing.
