# 8. Monitoring deep-dive (Prometheus + Grafana)

## 8.1 Why monitoring is a DevSecOps concern

Three reasons. Each is enough on its own.

1. **You can't defend what you can't see.** Detection requires visibility.
   An auth-bruteforce, a write-burst, an unusual 5xx spike — all are
   invisible without metrics. Monitoring turns a black-box server into a
   glass-box system.
2. **Mean time to detect (MTTD) drives mean time to recover (MTTR).** Studies
   consistently show MTTR scales linearly with MTTD; cutting MTTD in half
   roughly halves outage cost. Metrics + dashboards + alerts cut MTTD.
3. **Continuous feedback closes the DevSecOps loop.** A pipeline that ships
   code but doesn't observe what runs is "DevOps" at best, not DevSecOps.
   The post-deploy half of the lifecycle (the "Operate" + "Monitor" stages
   in the infinity diagram in section 1.3) is monitoring.

## 8.2 Architecture: the pull model

Prometheus uses a **pull** model. Every 5 seconds it makes an HTTP GET
request to a target's `/metrics` endpoint and stores whatever it gets back
as a set of time-series samples.

```
                ┌────────────────────────────────────────┐
                │  ssms_backend  (FastAPI + uvicorn)     │
                │                                        │
                │  prometheus-fastapi-instrumentator     │
                │   + prometheus-client Counters/Gauges  │
                │                                        │
                │           GET /metrics                 │
                │  ──────────────────────────────────►   │
                └────────────────────────────────────────┘
                                ▲
                                │  HTTP scrape every 5s
                                │
                ┌────────────────────────────────────────┐
                │  ssms_prometheus                       │
                │   reads /etc/prometheus/prometheus.yml │
                │   stores TSDB in /prometheus           │
                │   serves UI on :9090                   │
                └────────────────────────────────────────┘
                                ▲
                                │  Datasource HTTP queries
                                │
                ┌────────────────────────────────────────┐
                │  ssms_grafana                          │
                │   visualizes panels on :3000           │
                │   admin / GF_ADMIN_PASSWORD            │
                └────────────────────────────────────────┘
```

Pull is the right default for cattle-style microservices: targets are
discovered or statically listed; scraping is centralized; targets don't
need any push-credentials.

## 8.3 What gets collected

### 8.3.1 Auto-instrumented (by `prometheus-fastapi-instrumentator`)

For every HTTP request the middleware emits:

| Metric                              | Type      | Labels                                  |
|-------------------------------------|-----------|-----------------------------------------|
| `http_requests_total`               | Counter   | method, handler, status                 |
| `http_request_duration_seconds`     | Histogram | method, handler                         |
| `http_request_size_bytes`           | Histogram | method, handler                         |
| `http_response_size_bytes`          | Histogram | method, handler                         |

This gives you, out of the box:

- Throughput per route (`rate(http_requests_total[1m])`).
- p50 / p95 / p99 latency per route.
- 5xx error rate per route.

### 8.3.2 Custom counters from `utils/monitoring.py`

The SOC layer adds ~30 named counters. Greatest hits:

| Counter                              | Bumped when…                                       |
|--------------------------------------|----------------------------------------------------|
| `successful_logins_total`            | `/auth/login` returns 200                          |
| `failed_logins_total`                | `/auth/login` returns 401                          |
| `invalid_jwt_total`                  | Middleware sees a 401 from a JWT route             |
| `forbidden_requests_total`           | Any route returns 403                              |
| `auth_flood_alerts_total`            | Auth-fail threshold tripped                        |
| `soc_alerts_total{severity}`         | SOC alert persisted (info/warning/critical)        |
| `critical_soc_alerts_total`          | Alert with severity=critical persisted             |
| `quarantine_state`                   | Gauge: 0 idle, 1 in quarantine                     |
| `quarantine_trigger_total`           | Auto-quarantine fired                              |
| `quarantine_blocked_requests_total`  | Request blocked because system is in quarantine     |
| `unknown_barcode_total`              | Barcode scanned, not found in stock                |
| `barcode_scans_total`                | Any barcode scan                                   |
| `barcode_sell_operations_total`      | A sell scan succeeded                              |
| `barcode_restock_operations_total`   | A restock scan succeeded                           |
| `sales_total`                        | A sale recorded                                    |
| `orders_total` / `confirmed_orders_total` | Web order created / confirmed                 |
| `revenue_total`                      | Revenue (Float counter)                            |
| `low_stock_alerts_total`             | Item dropped below threshold                       |
| `expired_products_total`             | Stock with `expiry_date < today` detected          |
| `near_expiry_products_total`         | Stock about to expire                              |
| `api_errors_total` / `server_errors_total` | App / runtime errors                         |
| `anomaly_detection_total`            | SecurityMonitor returned any anomaly               |
| `request_spike_total` / `db_write_spike_total` | Specific spike types                     |
| `potential_ransomware_total`         | Write-burst triggered the "ransomware" rule        |

Every counter is **observable** by any well-formed PromQL query.

## 8.4 `monitoring/prometheus.yml`

```yaml
global:
  scrape_interval:     5s
  scrape_timeout:      4s
  evaluation_interval: 15s

scrape_configs:
  - job_name: ssms_backend
    metrics_path: /metrics
    static_configs:
      - targets:
          - backend:8000
        labels:
          service: ssms-backend
          env:     docker

  - job_name: prometheus
    static_configs:
      - targets:
          - localhost:9090
```

- `scrape_interval: 5s` — fast enough to spot 30-s bursts.
- `target: backend:8000` — resolved by Docker's embedded DNS to the backend
  container's IP. The string `backend` is the **compose service name**,
  which is why we kept that name even though `container_name` is
  `ssms_backend`.
- A second job (`prometheus`) scrapes itself, which gives us the Prometheus
  TSDB's own health metrics (lots of useful debug counters).
- `labels: {service, env}` are static labels attached to every sample from
  this job. Useful when you later have multiple environments scraped by the
  same Prometheus.

## 8.5 PromQL queries you should know

Run them at <http://localhost:9090/graph>:

| Question                               | Query                                                                          |
|----------------------------------------|--------------------------------------------------------------------------------|
| Requests per second by route           | `sum by (handler) (rate(http_requests_total[1m]))`                             |
| Login failure rate                     | `rate(failed_logins_total[5m])`                                                |
| 5xx rate                               | `rate(http_requests_total{status=~"5.."}[5m])`                                 |
| p95 request latency, ms                | `1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))` |
| Critical SOC alerts in the last 24h    | `increase(critical_soc_alerts_total[24h])`                                     |
| Currently quarantined?                 | `quarantine_state == 1`                                                        |
| Top 5 most-erroring routes             | `topk(5, sum by (handler) (rate(http_requests_total{status=~"5.."}[10m])))`     |
| Sales per minute                       | `rate(sales_total[1m]) * 60`                                                   |

In an oral demo, hitting `/metrics` to show the raw counters, then opening
Prometheus and running `rate(failed_logins_total[1m])` after hammering
`/auth/login` with bad creds in a curl loop, is the easiest way to show
the SOC layer working end-to-end.

## 8.6 Grafana

Grafana lives at `:3000` with the env-driven admin credentials. Bring it
up, log in, add a datasource:

- Type: **Prometheus**
- URL:  `http://prometheus:9090`
- Save & Test → green check.

Then build panels. A 5-minute starter dashboard:

| Panel                       | Query                                                                              |
|-----------------------------|------------------------------------------------------------------------------------|
| Requests / second (stack)   | `sum by (handler) (rate(http_requests_total[1m]))`                                 |
| p95 latency, ms             | `1000 * histogram_quantile(0.95, sum by (le, handler) (rate(http_request_duration_seconds_bucket[5m])))` |
| Failed logins / 5m          | `increase(failed_logins_total[5m])`                                                |
| Critical alerts             | `critical_soc_alerts_total`                                                        |
| Quarantine state            | `quarantine_state`                                                                 |
| Sales / minute              | `rate(sales_total[1m]) * 60`                                                       |

Grafana's auto-refresh (e.g. 5 s) makes the demo feel **alive**: hit the
API with curl, watch the panel tick.

## 8.7 Healthchecks vs metrics

These two terms get conflated. They are **different**:

- **Healthcheck** = single boolean ("am I alive?"). Used by Docker /
  Kubernetes / load balancers to decide whether to send traffic.
- **Metric** = a numeric time-series ("how many failed logins in the last
  minute?"). Used by humans + dashboards + alert rules.

This project has both:

```
/health    -> healthcheck    -> {"status":"ok","database":"mariadb","version":"1.0.0"}
/metrics   -> metrics         -> Prometheus text exposition format
```

`/health` is what Docker hits (10 s interval) to decide if the container
is healthy. `/metrics` is what Prometheus hits (5 s interval) to harvest
time-series.

## 8.8 Why this matters for DevSecOps grading

Mapped to common rubric points:

| Rubric item                          | Evidence                                                            |
|--------------------------------------|---------------------------------------------------------------------|
| Observability                        | Prometheus + Grafana + 30 custom counters                           |
| Continuous monitoring                | 5 s scrape interval, dashboards auto-refresh                        |
| Incident detection                   | SecurityMonitor + auto-quarantine                                   |
| Alerting                             | `persist_alert()` writes to DB + counter; can route to Alertmanager |
| Auditability                         | `inventory_logs` table + `alerts` table                             |
| Health-based deployment              | Compose `depends_on: service_healthy` + Ansible smoke-tests        |
| SLO / SLI material                   | Latency histograms, error counters, throughput counters            |
