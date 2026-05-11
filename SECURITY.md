# SSMS - DevSecOps & CI/CD Security

This document describes the security pipeline that gates every change to the
SSMS project, the tools that participate in it, and how to reproduce the
checks locally before pushing.

---

## 1. Pipeline overview

```
                                 push / pull_request
                                          |
            +-----------------------------+-----------------------------+
            |                             |                             |
            v                             v                             v
     ci-security.yml             docker-build-scan.yml          (Dependabot PRs
     (SAST + deps + lint)        (Trivy + SBOM + compose)       refresh weekly)
            |                             |
            |        both must succeed (workflow_run gate)
            +--------------+--------------+
                           |
                           v
                       deploy.yml
                       (Ansible -> EC2)
```

Three GitHub Actions workflows live in `.github/workflows/`:

| Workflow                | Triggers                              | Purpose                                                  |
|-------------------------|---------------------------------------|----------------------------------------------------------|
| `ci-security.yml`       | push, pull_request, manual            | Lint + Python SAST + dep CVEs + secret scan              |
| `docker-build-scan.yml` | push, pull_request, manual            | Build images, Trivy fs/image scans, SBOM, compose check  |
| `deploy.yml`            | manual or auto after both above pass  | Ansible-driven deploy to EC2                             |

Every Python and YAML file is parsed locally before commit; every PR triggers
all five SAST tools below; every successful run on `main` is eligible for
deployment to EC2.

---

## 2. Tools

### Static analysis (source code)

| Tool       | What it catches                                                                  | Where to look      |
|------------|----------------------------------------------------------------------------------|--------------------|
| flake8     | Style + obvious correctness bugs                                                 | Job logs           |
| Bandit     | Python-specific security smells (e.g. `subprocess shell=True`, weak hashes)      | Security tab + artifact `bandit-report` |
| Semgrep    | Rules-based SAST: OWASP Top 10, secret patterns, Dockerfile/Python smells        | Security tab + artifact `semgrep-report` |
| pip-audit  | Known CVEs in pinned Python deps (uses the official Python advisory DB)          | Artifact `pip-audit-report` |
| Gitleaks   | Committed secrets / API keys / private keys across the whole history             | Action summary     |

### Build & container security

| Tool             | What it catches                                                          |
|------------------|--------------------------------------------------------------------------|
| Trivy (fs scan)  | Misconfigurations + secrets in the working tree                          |
| Trivy (image)    | OS package CVEs in the built backend / frontend Docker images            |
| Trivy (SBOM)     | SPDX bill of materials for each image, archived as a CI artifact         |
| docker compose config | Static validation of the compose file before deploy                 |

### Image hardening (applied in `backend/Dockerfile` and `frontend/Dockerfile`)

- Multi-stage build for backend: compilers only in the build stage, not shipped to runtime
- Non-root user (`uid 10001` backend, `uid 101` frontend / nginx-unprivileged)
- `HEALTHCHECK` on every image
- `cap_drop: [ALL]` and `security_opt: no-new-privileges:true` in compose
- Minimal slim base images (`python:3.12-slim`, `nginxinc/nginx-unprivileged:1.27-alpine`)
- `tini` as PID 1 in the backend for proper signal forwarding

---

## 3. Failure thresholds

| Tool           | Build fails on                                          |
|----------------|---------------------------------------------------------|
| flake8         | Any violation (project rule)                            |
| Bandit         | Any `HIGH` severity finding                             |
| Semgrep        | Rules in `p/ci`, `p/security-audit`, `p/owasp-top-ten` (advisory; surfaces in Security tab) |
| pip-audit      | Any vulnerable Python dependency                        |
| Trivy (image)  | Any `CRITICAL` severity with a known fix                |
| Trivy (fs)     | `HIGH` and `CRITICAL` misconfig/secret findings         |

Lower-severity findings are still uploaded as SARIF so they show up in the
"Code scanning" view of the GitHub Security tab, but they don't break CI.

---

## 4. Required GitHub Secrets

Add these under **Settings -> Secrets and variables -> Actions -> New repository secret**.

### Required for `deploy.yml`

| Secret                  | Example                                  | Notes                                              |
|-------------------------|------------------------------------------|----------------------------------------------------|
| `EC2_HOST`              | `13.39.86.185`                           | Public IP / DNS of the EC2 produced by Terraform   |
| `EC2_SSH_USER`          | `ubuntu`                                 | SSH login user                                     |
| `EC2_SSH_KEY`           | `-----BEGIN OPENSSH PRIVATE KEY-----...` | Paste the **entire** content of `ssms-key.pem`     |
| `SSMS_JWT_SECRET`       | 32 random bytes, hex/base64              | Real JWT secret -- overrides the demo placeholder  |
| `SSMS_DB_PASSWORD`      | `<strong password>`                      | MariaDB application user password                  |
| `SSMS_DB_ROOT_PASSWORD` | `<strong password>`                      | MariaDB root password                              |
| `GF_ADMIN_PASSWORD`     | `<strong password>`                      | Grafana admin password                             |

### Optional

| Secret                | Why you might want it                                     |
|-----------------------|-----------------------------------------------------------|
| `SEMGREP_APP_TOKEN`   | Push findings to a Semgrep AppSec Platform org            |
| `SLACK_WEBHOOK_URL`   | If you wire Slack notifications into the workflows        |

Generate strong values quickly:
```
openssl rand -base64 32        # JWT_SECRET
openssl rand -base64 24        # DB / Grafana passwords
```

---

## 5. Running the scans locally

```bash
# Python virtual env
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pip install bandit[sarif] semgrep pip-audit flake8

# Lint + Python SAST
flake8 backend/app
bandit -r backend/app -s B311
semgrep --config p/ci --config p/security-audit --config p/python backend/app

# Dependency CVEs
pip-audit -r backend/requirements.txt --strict

# Trivy filesystem
docker run --rm -v "$PWD":/scan aquasec/trivy fs --severity HIGH,CRITICAL --ignore-unfixed /scan

# Trivy image (build first)
docker build -t ssms/backend:dev ./backend
docker run --rm aquasec/trivy image --severity CRITICAL,HIGH --ignore-unfixed ssms/backend:dev

# Gitleaks
docker run --rm -v "$PWD":/scan zricethezav/gitleaks:latest detect --source /scan --config /scan/.gitleaks.toml

# Compose static validation
docker compose -f docker-compose.yml config --quiet
```

---

## 6. Hardening checklist still on the roadmap

- [ ] Move runtime secrets to AWS SSM Parameter Store / Secrets Manager (`get_parameter` at boot)
- [ ] Pin every base image by digest (`@sha256:...`) instead of tag
- [ ] Add CodeQL workflow for advanced dataflow SAST
- [ ] Sign images with cosign + verify in deploy step
- [ ] Add an OpenAPI fuzzer (e.g. Schemathesis) once the API surface stabilizes
- [ ] Front the EC2 with Caddy + Let's Encrypt for TLS on 443

---

## 7. Reporting a vulnerability

If you find a real security issue in this codebase, please email the project
owner privately rather than opening a public issue. We'll acknowledge within
72 hours and coordinate a fix before disclosure.
