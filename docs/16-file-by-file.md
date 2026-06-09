# 16. File-by-file deep-dive

This section annotates every important file in the repository. It's
intended as a reference: jump to a path you'd be asked to defend.

## 16.1 Repository tree (curated)

```
.
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci-security.yml
│       ├── docker-build-scan.yml
│       ├── deploy.yml
│       └── devsecops.yml          (deprecated stub)
├── ansible/
│   ├── ansible.cfg
│   ├── inventory.ini
│   ├── playbook.yml
│   ├── requirements.yml
│   ├── README.md
│   ├── group_vars/all.yml
│   └── roles/
│       ├── common/
│       │   ├── tasks/main.yml
│       │   ├── defaults/main.yml
│       │   └── handlers/main.yml
│       ├── docker/
│       │   ├── tasks/main.yml
│       │   ├── defaults/main.yml
│       │   └── handlers/main.yml
│       └── ssms/
│           ├── tasks/main.yml
│           ├── defaults/main.yml
│           ├── handlers/main.yml
│           └── templates/env.j2
├── backend/
│   ├── Dockerfile                 (multi-stage, non-root, tini)
│   ├── requirements.txt
│   └── app/                       (FastAPI source — see section 6)
├── frontend/
│   ├── Dockerfile                 (nginx-unprivileged)
│   ├── index.html, shop.html, scanner.html
│   ├── app.js, shop.js
│   └── style.css, shop.css
├── monitoring/
│   └── prometheus.yml
├── terraform/
│   ├── provider.tf
│   ├── main.tf
│   ├── outputs.tf
│   └── terraform.tfstate          (gitignored)
├── docs/                          (this folder)
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .gitleaks.toml
├── .semgrepignore
├── .trivyignore
├── .flake8
├── README.md
└── SECURITY.md
```

## 16.2 The 25 files that matter most

### 16.2.1 `terraform/main.tf`

The only place AWS resources are declared. Three blocks:

- `data "aws_ami" "ubuntu"` — looks up Ubuntu 24.04 amd64 latest.
- `resource "aws_security_group" "ssms_sg"` — opens 22, 80, 3000, 9090.
- `resource "aws_instance" "ssms_vm"` — t2.micro, key `ssms-key`,
  user_data bootstrap.

See section 3.3 for line-by-line.

### 16.2.2 `terraform/provider.tf`

Pins `hashicorp/aws ~> 5.0`, region `eu-west-3`.

### 16.2.3 `terraform/outputs.tf`

Single `public_ip` output.

### 16.2.4 `ansible/playbook.yml`

```
hosts: ssms
become: true
pre_tasks: wait_for_connection, dpkg lock wait
roles: [common, docker, ssms]
post_tasks: print URL summary
```

See section 4 for the orchestration logic.

### 16.2.5 `ansible/inventory.ini`

Single host group `[ssms]` with `ssms-prod ansible_host=...`. Connection
defaults (ssh user, key path, python interpreter) live in `[ssms:vars]`.

### 16.2.6 `ansible/group_vars/all.yml`

The source of truth for project-wide variables: repo URL, branch, env
vars, ports, smoke-test URLs. Override at runtime with `-e`.

### 16.2.7 `ansible/roles/common/tasks/main.yml`

Timezone, apt update (cached 1h), base packages, UFW deny/allow setup,
explicit port openings (22 / 80 / 8000 / 9090 / 3000), enable UFW.

### 16.2.8 `ansible/roles/docker/tasks/main.yml`

Add Docker apt keyring (dearmored, idempotent via `creates:`), add
`docker.list`, install `docker-ce` + `docker-compose-plugin`, enable
service, add `ubuntu` to docker group, verify with `docker --version`
and `docker compose version`.

### 16.2.9 `ansible/roles/ssms/tasks/main.yml`

Ensure `/opt/ssms` exists, git clone the repo as `ubuntu`, render
`.env` from `templates/env.j2`, run `docker_compose_v2_pull`, run
`docker_compose_v2` `up -d --wait`, smoke-test `/health`, `/metrics`, `/`.

### 16.2.10 `ansible/roles/ssms/templates/env.j2`

```
{% for k, v in ssms_env.items() %}
{{ k }}={{ v }}
{% endfor %}
```

Iterates the dict from `group_vars/all.yml`. The `-e ssms_env.JWT_SECRET=...`
override in CI updates that dict before this renders.

### 16.2.11 `backend/Dockerfile`

Multi-stage build. Builder stage installs gcc/libffi, creates
`/opt/venv`, pip-installs `requirements.txt`. Runtime stage copies the
venv, installs `curl` + `tini`, creates user `app` (uid 10001),
`USER app:app`, healthcheck on `/health`, `tini` as PID 1, `uvicorn` as
CMD. See section 5.3 for line-by-line.

### 16.2.12 `backend/requirements.txt`

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
sqlalchemy==2.0.36
pymysql==1.1.1
cryptography==43.0.3
prometheus-client==0.21.1
prometheus-fastapi-instrumentator==7.0.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.0.1
python-multipart==0.0.20
```

Every version pinned. Notable: `bcrypt==4.0.1` because passlib 1.7.4 is
incompatible with bcrypt 4.1+; `cryptography` is explicit because
PyMySQL needs it for `caching_sha2_password` auth.

### 16.2.13 `backend/app/main.py`

The FastAPI factory. Sections discussed: 6.3. Notable lines:

- `Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)`
- `app.add_middleware(MonitoringMiddleware)`
- Static mount for `/static`, `/`, `/shop`, `/scanner` if frontend dir found.

### 16.2.14 `backend/app/core/config.py`

`Settings` dataclass, frozen, every field has env-var override + safe
default.

### 16.2.15 `backend/app/core/database.py`

Engine factory: MariaDB primary with `pool_pre_ping`, retries 10× 2s,
SQLite fallback. `active_backend_name()` helper. Section 6.5.

### 16.2.16 `backend/app/core/security.py`

bcrypt + JWT helpers. `get_current_user` dependency. `require_role`
factory.

### 16.2.17 `backend/app/utils/monitoring.py`

~30 Prometheus counters and the `MonitoringMiddleware`. Section 6.6.

### 16.2.18 `backend/app/utils/logger.py`

`SecurityMonitor` — the in-memory anomaly detector with quarantine
logic. `persist_alert` helper. Section 6.6.

### 16.2.19 `backend/app/utils/seed.py`

Idempotent seeders for users (admin, employee), 20 products with valid
EAN-13 barcodes, ~50 sales, 120 CCTV events, ~12 web orders. Makes the
demo dashboards non-empty on first boot.

### 16.2.20 `frontend/Dockerfile`

`FROM nginxinc/nginx-unprivileged:1.27-alpine`, `USER 101`,
`COPY --chown=101:101 . /usr/share/nginx/html`, healthcheck via `wget`.

### 16.2.21 `docker-compose.yml`

Five services on `ssms_net`, three named volumes, env-var-driven
secrets, `cap_drop: [ALL]` + `no-new-privileges:true` on hardened
services, host port mapping `80:8080` for frontend. Section 5.4.

### 16.2.22 `monitoring/prometheus.yml`

5s scrape interval, target `backend:8000`, second job for Prometheus
itself.

### 16.2.23 `.github/workflows/ci-security.yml`

5 jobs (lint, bandit, semgrep, pip-audit, gitleaks), SARIF uploads,
artifact uploads, build fails on Bandit HIGH. Section 9.3.

### 16.2.24 `.github/workflows/docker-build-scan.yml`

`trivy-fs` + matrix `build-scan-image` + `compose-validate`. Section
9.4.

### 16.2.25 `.github/workflows/deploy.yml`

`workflow_run` gate + `workflow_dispatch` manual trigger. Ansible
playbook run with secrets injected. Section 9.5.

## 16.3 Misc supporting files

- `.gitignore` — blocks `.env`, swap files, `*.db`, tfstate, scan outputs.
- `.env.example` — documents the secret contract.
- `.gitleaks.toml` — extends default rules with project allow-list.
- `.semgrepignore` — paths to skip.
- `.trivyignore` — placeholder for CVE waivers (none currently).
- `.flake8` — flake8 config (line length, ignored rules).
- `SECURITY.md` — security pipeline summary + required GitHub Secrets.
- `README.md` — top-level overview, quick-start, CI/CD table.

## 16.4 Files you'll never need to touch in normal operation

- `terraform.tfstate` — managed by Terraform; never edit.
- `.git/*` — version control state.
- `backend/.venv/*` — local Python env (gitignored).
- `terraform/.terraform/*` — provider binaries (gitignored).
- `*/__pycache__/*` — Python bytecode (gitignored).

If anything in this list is in a diff during a code review, that's a
red flag — investigate why.

## 16.5 Where to look first when something is broken

| Symptom                                  | First file to read                                              |
|------------------------------------------|-----------------------------------------------------------------|
| `docker compose up` fails                | `docker-compose.yml`                                            |
| Backend crashes on boot                  | `backend/app/main.py`, `backend/app/core/database.py`           |
| Auth not working                         | `backend/app/core/security.py`, `backend/app/routers/auth.py`   |
| `/metrics` empty                         | `backend/app/utils/monitoring.py`, `backend/app/main.py`        |
| Prometheus shows target DOWN             | `monitoring/prometheus.yml`, network setup in `docker-compose.yml` |
| Grafana can't query Prometheus           | Datasource URL in Grafana UI (`http://prometheus:9090`)         |
| Ansible can't SSH                        | `ansible/inventory.ini`, GitHub Secret `EC2_SSH_KEY`            |
| Ansible Docker install fails             | `ansible/roles/docker/tasks/main.yml`                           |
| `docker compose up` says "image not found" | `docker-compose.yml` `build:` paths                           |
| Trivy fails CI                           | The Trivy step's annotation in the run, then the Dockerfile     |
| Bandit fails CI                          | Bandit SARIF artifact + Security tab                            |
| Gitleaks fails CI                        | The line called out in the run + `.gitleaks.toml`               |
