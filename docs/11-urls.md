# 11. Project URLs

Every URL the stack exposes, what it does, and who uses it.

## 11.1 Quick map

| URL                                    | Container       | Who uses it                      |
|----------------------------------------|------------------|----------------------------------|
| `http://<EC2>/`                        | ssms_frontend    | End customer / operator UI       |
| `http://<EC2>/shop`                    | ssms_frontend    | End customer (web orders)        |
| `http://<EC2>/scanner`                 | ssms_frontend    | Employee on tablet               |
| `http://<EC2>:8000/`                   | ssms_backend     | (Fallback) same UI via API server |
| `http://<EC2>:8000/docs`               | ssms_backend     | Developer / grader               |
| `http://<EC2>:8000/redoc`              | ssms_backend     | Developer / grader               |
| `http://<EC2>:8000/openapi.json`       | ssms_backend     | API client generators            |
| `http://<EC2>:8000/health`             | ssms_backend     | Docker healthcheck, smoke tests  |
| `http://<EC2>:8000/metrics`            | ssms_backend     | Prometheus scrape                |
| `http://<EC2>:8000/auth/*`             | ssms_backend     | Login / register / `me`           |
| `http://<EC2>:8000/sales/*`            | ssms_backend     | Sales CRUD + KPI                 |
| `http://<EC2>:8000/stock/*`            | ssms_backend     | Stock CRUD + barcode scan        |
| `http://<EC2>:8000/inventory/*`        | ssms_backend     | Inventory audit log feed         |
| `http://<EC2>:8000/cctv/*`             | ssms_backend     | CCTV events + zone analytics     |
| `http://<EC2>:8000/orders/*`           | ssms_backend     | Web orders                       |
| `http://<EC2>:8000/promotions/*`       | ssms_backend     | Promotion suggestions            |
| `http://<EC2>:8000/dashboard/*`        | ssms_backend     | Operator dashboard summary       |
| `http://<EC2>:8000/analytics/*`        | ssms_backend     | Analytics endpoints              |
| `http://<EC2>:8000/soc/*`              | ssms_backend     | SOC alert feed                   |
| `http://<EC2>:8000/security/status`    | ssms_backend     | SOC dashboard                    |
| `http://<EC2>:8000/security/quarantine/release` | ssms_backend | Operator releases quarantine |
| `http://<EC2>:9090/`                   | ssms_prometheus  | Prometheus expression browser    |
| `http://<EC2>:9090/targets`            | ssms_prometheus  | Scrape target health             |
| `http://<EC2>:9090/graph?...`          | ssms_prometheus  | Ad-hoc PromQL                    |
| `http://<EC2>:3000/`                   | ssms_grafana     | Grafana login → dashboards       |
| `http://<EC2>:3000/datasources`        | ssms_grafana     | Configure Prometheus as DS       |

## 11.2 Detail

### 11.2.1 Frontend (`:80`)

- `/` — operator dashboard. Vanilla HTML, fetches `/dashboard/summary`,
  `/sales/kpi`, `/stock/kpi`, `/soc/alerts` and renders cards + tables.
  Requires the user to be logged in (token in localStorage).
- `/shop` — public catalogue + cart. No JWT required (the click-and-collect
  flow is anonymous; the order gets a public ID and the customer can come
  fetch it).
- `/scanner` — barcode scanner UI for employees. Requires JWT.

### 11.2.2 Backend (`:8000`)

`/docs` is the **single most useful URL** for a grader. It's the auto-
generated Swagger UI listing every endpoint, its parameters, its response
schema, and a "Try it out" button. Hand it to a teacher and they can
exercise the whole API in 30 seconds.

`/health` is the smoke-test URL:

```json
{ "status": "ok", "version": "1.0.0", "database": "mariadb" }
```

`/metrics` is the Prometheus scrape target. Hitting it manually:

```
# HELP http_requests_total ...
http_requests_total{handler="/health",method="GET",status="2xx"} 142.0
...
# HELP failed_logins_total Total failed login attempts
failed_logins_total 3.0
...
# HELP quarantine_state Current quarantine state (0=off,1=on)
quarantine_state 0.0
```

### 11.2.3 Prometheus (`:9090`)

- `/targets` — list of scrape jobs, last scrape duration, last scrape time,
  up/down. First place to check if metrics are missing.
- `/graph` — the ad-hoc PromQL UI. Paste a query, hit "Execute", switch to
  the Graph tab to see a chart.
- `/alerts` — alert rules (we don't ship any yet — extending Prometheus with
  alert rules + Alertmanager is the next maturity step).

### 11.2.4 Grafana (`:3000`)

- `/` (after login) — landing page. Empty until a dashboard is created.
- `/datasources` — where you wire `http://prometheus:9090` as the data
  source. This is the only manual step in the demo.
- `/dashboards` — list of dashboards. JSON-imported or built panel by panel.

## 11.3 Why each URL exists

| URL category               | Reason                                                              |
|----------------------------|---------------------------------------------------------------------|
| `/`, `/shop`, `/scanner`   | Human-facing UIs                                                    |
| `/docs`, `/redoc`          | API self-documentation — saves writing API docs in the README       |
| `/openapi.json`            | Machine-readable spec — client generators eat this                  |
| `/health`                  | Boot ordering + smoke-test target                                   |
| `/metrics`                 | Observability                                                       |
| `/auth/*`                  | Identity                                                            |
| Domain CRUD endpoints      | The business                                                        |
| `/security/*`              | Self-defense surface                                                |
| `/soc/*`                   | Audit feed for graders to see SOC alerts persisted                  |
| Prometheus `/targets`      | Operational diagnostic                                              |
| Grafana                    | Visualization layer for non-technical viewers                       |
