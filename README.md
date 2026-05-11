# SSMS - Smart Store Management System

End-to-end retail / SOC demo stack: FastAPI backend, MariaDB, static Nginx
frontend, Prometheus + Grafana monitoring, deployed to AWS EC2 via Terraform
and Ansible, gated by a DevSecOps pipeline on GitHub Actions.

```
+----------------+        +------------+        +----------------+
| GitHub Actions | -----> |  Ansible   | -----> |   AWS EC2      |
|  CI + scans    |  pass  |  playbook  |  ssh   |  Docker stack  |
+----------------+        +------------+        +----------------+
                                                       |
                                                       v
                          +------+   +---------+   +----------+   +---------+
                          | nginx|   | FastAPI |   | MariaDB  |   | Grafana |
                          |  :80 |<->|  :8000  |-->|  :3306   |   |  :3000  |
                          +------+   +---------+   +----------+   +---------+
                                          |
                                          v
                                   +------------+
                                   | Prometheus |
                                   |   :9090    |
                                   +------------+
```

## Quick start (local)

```bash
cp .env.example .env       # then edit -- never commit your .env
docker compose up -d --build
```

Open:
- Frontend:   http://localhost/
- Backend:    http://localhost:8000/   (`/docs`, `/health`, `/metrics`)
- Prometheus: http://localhost:9090/
- Grafana:    http://localhost:3000/   (admin / value of `GF_ADMIN_PASSWORD`)

## Layout

```
.
├── backend/           # FastAPI app (hardened multi-stage Dockerfile)
├── frontend/          # Static site served by nginx-unprivileged
├── monitoring/        # prometheus.yml scrape config
├── terraform/         # AWS EC2 provisioning
├── ansible/           # roles/common, roles/docker, roles/ssms + playbook.yml
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci-security.yml
│       ├── docker-build-scan.yml
│       └── deploy.yml
├── docker-compose.yml
├── .env.example       # contract for the .env compose reads
├── SECURITY.md        # security pipeline, tools, threshold + secrets
└── README.md          # you are here
```

## Deployment flow

1. `terraform apply` in `./terraform/` provisions the EC2 instance.
2. Add the instance's public IP to `ansible/inventory.ini` (or wire the
   Terraform output into it -- see `ansible/README.md`).
3. `ansible-playbook -i inventory.ini playbook.yml` does the rest: installs
   Docker, clones this repo on the EC2, renders `.env`, runs `docker compose
   up -d --wait`, and smoke-tests every URL.
4. On every push to `main`, GitHub Actions re-runs the same Ansible
   playbook from a runner, gated on the security scans passing.

## CI/CD security pipeline

See [`SECURITY.md`](SECURITY.md) for the full description.

| Stage                  | Tool(s)                                                                                       |
|------------------------|-----------------------------------------------------------------------------------------------|
| Lint                   | flake8                                                                                        |
| Python SAST            | Bandit (SARIF -> Security tab)                                                                |
| Rules-based SAST       | Semgrep (`p/ci`, `p/security-audit`, `p/owasp-top-ten`, `p/python`, `p/dockerfile`)           |
| Dependency CVEs        | pip-audit                                                                                     |
| Secrets scan           | Gitleaks (whole git history)                                                                  |
| Container scan         | Trivy (filesystem + image), CRITICAL fails the build                                          |
| SBOM                   | Trivy SPDX-JSON, uploaded as artifact                                                         |
| Compose validation     | `docker compose config`                                                                       |
| Image hardening        | Multi-stage, non-root, `tini`, `cap_drop:[ALL]`, `no-new-privileges`, `HEALTHCHECK`           |
| Deploy gate            | `workflow_run` on `ci-security` + `docker-build-scan`                                         |
| Deploy                 | Ansible playbook over SSH from the runner                                                     |
| Dep updates            | Dependabot (pip, docker, github-actions)                                                      |

### GitHub Secrets you must configure manually

Listed in [`SECURITY.md` section 4](SECURITY.md#4-required-github-secrets).
Short version: `EC2_HOST`, `EC2_SSH_USER`, `EC2_SSH_KEY`, `SSMS_JWT_SECRET`,
`SSMS_DB_PASSWORD`, `SSMS_DB_ROOT_PASSWORD`, `GF_ADMIN_PASSWORD`.

### Running the security scans locally

See [`SECURITY.md` section 5](SECURITY.md#5-running-the-scans-locally).
