# 2. Full architecture explanation

## 2.1 Bird's-eye view

```
                            INTERNET
                                │
                                ▼
                    ┌──────────────────────┐
                    │  AWS Security Group  │   ingress 22, 80, 3000, 9090
                    │  (acts as firewall)  │   egress all
                    └──────────────────────┘
                                │
                                ▼
            ┌─────────────────────────────────────────┐
            │            AWS EC2 (Ubuntu)             │
            │   public IP, port-mapped to host ports  │
            │                                         │
            │   ┌─────────────────────────────────┐   │
            │   │  Docker engine + Compose plugin │   │
            │   │                                 │   │
            │   │   Network: ssms_net (bridge)    │   │
            │   │   ┌────────────────────────┐    │   │
            │   │   │  ssms_frontend (nginx) │    │   │
            │   │   │  8080 internal, 80 ext │◄───┼───┼─── http://<EC2>/
            │   │   └────────────────────────┘    │   │
            │   │            │ XHR/fetch          │   │
            │   │            ▼                    │   │
            │   │   ┌────────────────────────┐    │   │
            │   │   │  ssms_backend (uvicorn │    │   │
            │   │   │  + FastAPI)            │    │   │
            │   │   │  8000                  │◄───┼───┼─── http://<EC2>:8000/
            │   │   └────────────────────────┘    │   │   /docs /metrics /health
            │   │            │ SQLAlchemy/pymysql │   │
            │   │            ▼                    │   │
            │   │   ┌────────────────────────┐    │   │
            │   │   │  ssms_mariadb          │    │   │
            │   │   │  3306                  │    │   │
            │   │   └────────────────────────┘    │   │
            │   │                                 │   │
            │   │   ┌────────────────────────┐    │   │
            │   │   │  ssms_prometheus       │◄───┼───┼─── http://<EC2>:9090/
            │   │   │  9090, scrapes backend │    │   │
            │   │   │  every 5s              │    │   │
            │   │   └────────────────────────┘    │   │
            │   │            ▲ datasource         │   │
            │   │   ┌────────────────────────┐    │   │
            │   │   │  ssms_grafana          │◄───┼───┼─── http://<EC2>:3000/
            │   │   │  3000                  │    │   │
            │   │   └────────────────────────┘    │   │
            │   └─────────────────────────────────┘   │
            └─────────────────────────────────────────┘
                                ▲
                                │ SSH (port 22, key auth only)
                                │
                    ┌──────────────────────┐
                    │  Ansible from CI or  │
                    │  from a workstation  │
                    └──────────────────────┘
```

## 2.2 Layered view (request lifecycle)

A request from a browser to the SSMS shop page travels through this many
moving parts:

```
[Browser]
    │
    │  1.  HTTP GET http://<EC2>/  (host port 80)
    ▼
[Linux netfilter / UFW]
    │  rule "allow 80/tcp" -> pass
    ▼
[Docker port publication]
    │  host :80  ->  ssms_frontend:8080
    ▼
[ssms_frontend container, nginx-unprivileged]
    │  serves index.html from /usr/share/nginx/html
    │
    │  2.  Browser executes shop.js, calls fetch('http://<EC2>:8000/inventory')
    ▼
[Linux netfilter / UFW] allow 8000/tcp
    │
[Docker port publication] host :8000 -> ssms_backend:8000
    ▼
[ssms_backend container, uvicorn ASGI server]
    │
    │  3.  Uvicorn hands the ASGI scope to FastAPI app object
    ▼
[FastAPI middleware chain]
    │  - MonitoringMiddleware: counts request, runs SecurityMonitor.analyze()
    │  - CORSMiddleware:       inspects Origin, sets CORS headers
    ▼
[Route resolution]
    │  /inventory -> inventory.router -> get_inventory_logs()
    ▼
[Dependency injection: get_db -> SessionLocal()]
    │  SQLAlchemy session opens a pooled connection
    ▼
[Service layer: inventory_service]
    │  SELECT ... FROM inventory_logs WHERE ...
    ▼
[pymysql] over Docker bridge network to ssms_mariadb:3306
    │
[MariaDB] returns rows
    │
[Response builder]
    │  - service maps rows -> pydantic schema
    │  - FastAPI serializes to JSON
    ▼
[MonitoringMiddleware] adds X-Process-Time-ms header, increments counters
    ▼
[uvicorn writes HTTP/1.1 response back through Docker network -> kernel -> Browser]
```

In parallel, **once every 5 seconds**:

```
[Prometheus container]
    │  GET http://backend:8000/metrics
    ▼
[FastAPI Instrumentator middleware] -> serializes all Counter / Gauge / Histogram
    │  values as Prometheus text format
    ▼
[Prometheus] stores time-series in /prometheus volume
    ▲
    │  GET /api/datasources/proxy/...
    │
[Grafana] queries Prometheus, renders dashboard panels in the browser
```

## 2.3 Component responsibilities

### Frontend (`frontend/` → image `ssms/frontend:latest`)

Plain HTML/CSS/JS pages served by Nginx:

- `index.html` — operator dashboard (stock, sales, alerts).
- `shop.html` — anonymous web ordering UI for the click-and-collect flow.
- `scanner.html` — barcode-scanner page.
- `app.js`, `shop.js` — vanilla JS, talks to the backend via `fetch`.

There is **no server-side rendering** and **no reverse-proxy**: the frontend
and backend are independent containers, and the browser makes cross-origin
calls (allowed by the backend's permissive CORS in dev — would be tightened
in production).

### Backend (`backend/` → image `ssms/backend:latest`)

A standard FastAPI app split into layers:

```
app/
├── main.py             # app factory, lifespan, middleware, static mounts
├── core/
│   ├── config.py       # Settings dataclass, env-driven
│   ├── database.py     # SQLAlchemy engine, retry-with-fallback resolver
│   └── security.py     # bcrypt + JWT helpers, get_current_user dependency
├── models/             # SQLAlchemy ORM (users, sales, stock, alerts, cctv, orders, inventory_logs)
├── schemas/            # Pydantic request/response models (one per domain)
├── services/           # business logic, never touches FastAPI
├── routers/            # FastAPI APIRouters, the only place that knows about HTTP
└── utils/
    ├── logger.py       # logger + SecurityMonitor (anomaly detector)
    ├── monitoring.py   # MonitoringMiddleware + Prometheus counters/gauges
    └── seed.py         # idempotent seed data so the demo dashboards aren't empty
```

This is the conventional FastAPI layering. Routers handle HTTP; services
handle business logic; models persist; schemas validate. The seam between
each layer is a single import edge, which keeps things testable.

### Database (`mariadb:11` from Docker Hub)

A single MariaDB instance, addressed by other containers as `mariadb:3306`
on the `ssms_net` bridge network. Data lives in the named volume
`mariadb_data` (not a bind mount — survives `docker compose down`, dies on
`down -v`). Healthcheck pings the server every 5 s; backend won't start
until MariaDB reports `service_healthy`.

### Monitoring stack

- **Prometheus** scrapes `http://backend:8000/metrics` every 5 s, persists
  to the `prometheus_data` named volume, exposes its UI on :9090.
- **Grafana** runs separately, configured with admin/admin (overridable
  via env vars), uses Prometheus as its datasource, exposes its UI on :3000.

### CI/CD (`.github/workflows/`)

Three workflows orchestrate the lifecycle. Detailed in section 9.

### IaC + CM (`terraform/`, `ansible/`)

- **Terraform** provisions the EC2 + security group + AMI lookup. Output =
  public IP.
- **Ansible** SSHs to that IP and: installs Docker, clones the repo, renders
  `.env`, runs `docker compose up -d --wait`, runs smoke tests.

## 2.4 Network topology

There are **two networks** at play:

1. **Public internet** ↔ **EC2 host's public IP**, filtered by the AWS
   security group. Only TCP ports 22, 80, 3000, 8000, 9090 are open.
2. **Docker bridge `ssms_net`** inside the EC2. Containers reach each other
   by service-name DNS (`backend`, `mariadb`, `prometheus`). Nothing on this
   network is reachable from outside unless a port is explicitly published.

That second layer is important: even though MariaDB is exposed on `3306:3306`
in compose (so an operator can connect with `mysql -h <EC2>` for debugging),
the AWS security group **does not** open 3306, so a remote attacker still
can't reach it. The UFW firewall on the EC2 itself also blocks 3306 (see
`ansible/group_vars/all.yml`).

## 2.5 Data flow vignette: a barcode scan

This is the most security-relevant flow and the one to demo in an oral.

```
1. Employee opens http://<EC2>/scanner in a tablet browser.
2. Browser fetches scanner.html from the nginx frontend container.
3. Employee scans a barcode (the device emits keystrokes ending in Enter).
4. scanner.js does `POST /stock/scan` to the backend with {barcode, action:"sell"}.
5. MonitoringMiddleware:
     - increments request counter
     - records "db_write" event in SecurityMonitor
     - if write_rate > WRITE_BURST_THRESHOLD -> triggers quarantine
6. JWT bearer token from localStorage authenticates the user.
7. Router /stock/scan dispatches to stock_service.scan_product:
     - SELECT stock_item WHERE barcode = ?
     - UPDATE stock_item SET quantity = quantity - 1
     - INSERT INTO inventory_logs (...)
     - INSERT INTO sale_items (...) and bookkeep a Sale row
     - increments Prometheus counters (sales_total, barcode_sell_operations_total)
8. If item not found:
     - unknown_barcode_total counter increments
     - persist_alert("inventory", "warning", "Unknown barcode scanned")
9. Response goes back through the middleware -> the browser updates the UI.
10. Five seconds later Prometheus scrapes /metrics; Grafana panel "sales per minute" ticks up.
```

This single flow exercises auth, RBAC (only `employee`/`admin` may scan),
write monitoring, anomaly detection, alerting, metrics, and audit logging —
which is exactly what an evaluator wants to see live in a demo.
