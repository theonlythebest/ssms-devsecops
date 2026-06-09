# 1. Global project overview

## 1.1 What is SSMS?

**SSMS = Smart Store Management System.**

It is a small but realistic retail / Security Operations Center (SOC) backend.
The business domain is a brick-and-mortar shop:

- **Sales** through an electronic point of sale (EPOS): cashiers ring up items,
  sales are recorded with line items and totals.
- **Stock**: products with barcodes (valid EAN-13), expiry dates, low-stock thresholds.
- **Inventory log**: every barcode scan (sell / restock) is appended to an audit trail.
- **Web orders**: anonymous click-and-collect orders, items deducted from stock when confirmed.
- **CCTV analytics**: GDPR-safe zone-occupancy counts (no faces, no IDs — only "5 people in produce at 14:32").
- **Promotions**: automatic recommendations based on sale data and expiring stock.
- **Authentication**: JWT-secured login for two roles, `admin` and `employee`.
- **SOC layer**: every HTTP request goes through a security middleware that
  detects anomalies (auth flood, write burst, multi-vector attack patterns)
  and can automatically quarantine the API if it sees ransomware-shaped activity.

The point of SSMS isn't to be a real retail product. The point is to give every
DevSecOps practice something real to apply itself to — a backend with auth,
metrics, alerts, persistent storage, and a UI, so the pipeline and the
infrastructure have a concrete reason to exist.

## 1.2 What problem does the project solve?

The project demonstrates a **full DevSecOps lifecycle**, end-to-end, on a single
codebase:

1. Write code locally → it runs.
2. Push to GitHub → automated security gates evaluate it.
3. If the gates pass → automation deploys it to AWS.
4. Once it's deployed → monitoring observes it and alerts on misbehaviour.

Each step is reproducible, idempotent, and auditable. Anyone can clone the
repo, run `terraform apply` and `ansible-playbook`, and within ~10 minutes
have an identical stack running on their own EC2.

## 1.3 The DevSecOps philosophy used here

DevSecOps is not a tool. It's the practice of:

1. **Shifting security left**: move security checks as close to the developer
   as possible. The first SAST scan happens before the PR is merged, not after
   production is exploited.
2. **Automating everything**: humans copying files around or running scans
   manually is the bottleneck and the bug source. If a step can't be scripted,
   it can't be trusted in production.
3. **Defense in depth**: assume any single layer will fail. Stack many cheap
   controls (lint + SAST + dep scan + container scan + runtime hardening +
   network firewall) so one missed vulnerability doesn't cascade.
4. **Continuous feedback**: failure must be loud, fast, and visible (red
   pipeline icon, SARIF findings in the Security tab, Prometheus alerts).

This project applies that philosophy concretely. The diagram below maps the
canonical DevSecOps "infinity loop" to what we actually do.

```
       ┌──────────────────────────────────────────────────┐
       │                  PLAN / CODE                     │
       │  - feature branch                                │
       │  - .gitignore blocks secrets                     │
       │  - .env.example documents secret contract        │
       └──────────────────────────────────────────────────┘
                              │ git push
                              ▼
       ┌──────────────────────────────────────────────────┐
       │                BUILD / TEST / SECURE             │  ← shift left
       │  GitHub Actions (ci-security.yml)                │
       │   flake8, Bandit, Semgrep, pip-audit, Gitleaks   │
       │  GitHub Actions (docker-build-scan.yml)          │
       │   Buildx, Trivy fs/image/SBOM, compose validate  │
       └──────────────────────────────────────────────────┘
                              │ workflow_run gate
                              ▼
       ┌──────────────────────────────────────────────────┐
       │                  RELEASE / DEPLOY                │
       │  deploy.yml -> Ansible playbook over SSH         │
       │  Ansible idempotency guarantees the same state   │
       │  Terraform recreates the EC2 if needed           │
       └──────────────────────────────────────────────────┘
                              │
                              ▼
       ┌──────────────────────────────────────────────────┐
       │                 OPERATE / MONITOR                │
       │  Prometheus scrapes /metrics every 5s            │
       │  Grafana dashboards visualize trends             │
       │  Backend SecurityMonitor auto-quarantines on     │
       │  ransomware-like write bursts                    │
       └──────────────────────────────────────────────────┘
                              │ alerts / new requirements
                              ▼
       ┌──────────────────────────────────────────────────┐
       │                      LEARN                       │
       │  Dependabot opens PRs for vulnerable deps        │
       │  SARIF findings feed code-scanning insights      │
       └──────────────────────────────────────────────────┘
                              │
                              └─► back to PLAN
```

## 1.4 Why each technology was chosen

| Technology         | Why this one?                                                                                       |
|--------------------|-----------------------------------------------------------------------------------------------------|
| **FastAPI**        | Modern Python, async, automatic OpenAPI docs at `/docs`, native Pydantic validation. Great for SOC-style endpoints. |
| **MariaDB**        | MySQL-compatible, well-known by industry, free Docker image, easy to back up, easy to demo. Postgres would have worked too — we standardized on MariaDB after a migration. |
| **SQLAlchemy 2.x** | Industry-standard ORM. Lets us swap DB engines (we proved this by migrating Postgres → MariaDB). Built-in connection pooling. |
| **Nginx**          | Tiny static-file server, hardened image (`nginx-unprivileged`). Good demonstration of a separate web tier even when the API serves its own static fallback. |
| **Prometheus**     | The de-facto open-source metrics standard. Pull-based, simple scrape config, free.                  |
| **Grafana**        | Best-in-class dashboarding for Prometheus. Free, container-native, ships with auth.                 |
| **Docker / Compose** | Reproducible packaging + local orchestration. Compose v2 has healthchecks, restart policies, network isolation, capability dropping. |
| **Terraform**      | Declarative IaC, free for AWS, idempotent. Lets the EC2 be a "cattle" resource not a "pet".         |
| **Ansible**        | Agentless config management. SSH-only. Easy to read, great for Linux post-provisioning.             |
| **GitHub Actions** | Already where the code lives. SARIF integration with the Security tab is best-in-class.             |
| **Trivy**          | Free, fast, very good signal-to-noise for OS-layer CVEs. SARIF output, SBOM generation built in.    |
| **Bandit**         | Python-AST specific. Catches `subprocess shell=True`, hard-coded passwords, weak hashes.            |
| **Semgrep**        | Rules-based, multi-language, regularly updated rule packs (`p/owasp-top-ten`, `p/security-audit`).  |
| **Gitleaks**       | The gold standard for "did anyone commit a secret to the history?". Runs across all branches.       |
| **pip-audit**      | Maintained by PyPA. Cross-references our `requirements.txt` against the Python Packaging Advisory DB. |
| **Dependabot**     | Free, native to GitHub, opens PRs automatically when a dep has a CVE or a new release.              |

## 1.5 Constraints and non-goals

To keep the scope realistic the project explicitly does **not** include:

- HTTPS / TLS termination (would need a real DNS name + cert manager — out of scope).
- High availability (single EC2, no autoscaling group).
- Read replicas / DB clustering (single MariaDB container).
- Multi-tenant or multi-region.
- A production-grade IAM / RBAC model beyond two JWT roles.
- Real CCTV ingestion. The CCTV module simulates events for the dashboard.

These omissions are recorded as items on a hardening roadmap (see section 14).

## 1.6 Who is this project for?

- **An evaluator** judging DevSecOps maturity wants to see: pipelines wired up,
  SARIF in Security tab, hardened images, secrets out of source, IaC + CM,
  monitoring, documented threat model. All present.
- **A future developer** inheriting the project wants: a README, an architecture
  diagram, a "how do I deploy this" runbook, a place where every CVE/finding
  is triaged. All present (see `README.md`, `SECURITY.md`, this `docs/` folder).
- **An attacker** probing the public IP: they meet UFW, dropped capabilities,
  no-new-privileges, JWT-protected endpoints, auto-quarantine on write bursts,
  no secrets in source. The bar to get to anything interesting is high.
