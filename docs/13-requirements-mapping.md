# 13. DevSecOps rubric mapping

> **Note:** the project specification wasn't provided in the brief, so this
> section maps the project against a **standard DevSecOps rubric**
> (DevSecOps lifecycle stages × industry maturity model). When the official
> rubric is shared, each row can be re-anchored to the exact wording
> without changing the underlying evidence.

The rubric below is a synthesis of:

- The DoD Enterprise DevSecOps Reference Design lifecycle stages.
- The OWASP DevSecOps Maturity Model (DSOMM).
- The NIST SP 800-218 Secure Software Development Framework (SSDF).
- The Microsoft / Google "DevSecOps requirements" checklist commonly used
  in academic capstones.

For every requirement the table shows: **what's required → does this
project satisfy it → exactly how**.

## 13.1 Plan / Code

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Source code under version control               | ✅        | GitHub repository                                    |
| `.gitignore` excludes secrets, build artifacts  | ✅        | `.gitignore` blocks `.env`, swap files, SQLite, etc.|
| Branch-based dev workflow + PRs                 | ✅        | feature branches → PR → merge to `main`             |
| Code review enforced                            | ⚠️         | Recommended via branch protection rules (manual setup) |
| Architecture / decision documentation           | ✅        | `README.md`, `SECURITY.md`, `docs/` (this folder)   |
| Security policy file                            | ✅        | `SECURITY.md` includes a disclosure section          |

## 13.2 Build

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Reproducible builds                             | ✅        | Pinned Python deps; pinned base image; Docker buildx |
| Multi-stage Docker build                        | ✅        | `backend/Dockerfile` builder + runtime stages        |
| Build runs in CI, not on developer laptop       | ✅        | `docker-build-scan.yml`                              |
| Image scan during build                         | ✅        | Trivy image scan, SARIF to Security tab              |
| SBOM produced per artifact                      | ✅        | Trivy SPDX-JSON, uploaded as artifact                |
| Build fails on critical vulnerabilities         | ✅        | Trivy `severity: CRITICAL, exit-code: 1`             |
| Cached layers / build cache                     | ✅        | GitHub Actions cache via `cache-to: type=gha`        |

## 13.3 Test

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Static linting                                  | ✅        | flake8                                               |
| SAST (Static Application Security Testing)      | ✅        | Bandit + Semgrep                                     |
| SCA (Software Composition Analysis)             | ✅        | pip-audit; Dependabot                                |
| Secret scanning                                 | ✅        | Gitleaks; Trivy fs secret scanner                    |
| IaC / Docker misconfig scanning                 | ✅        | Trivy fs `misconfig` scanner                         |
| Container image scanning                        | ✅        | Trivy image scan per service                         |
| Unit tests                                      | ⚠️         | Project structure is unit-test-ready; tests not included by default |
| DAST (Dynamic App Security Testing)             | ❌        | Not included — recommended next step is OWASP ZAP    |
| Compose / IaC validation                        | ✅        | `docker compose config --quiet`; Terraform plan      |

## 13.4 Release / Deploy

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Infrastructure as Code                          | ✅        | Terraform (`terraform/main.tf`)                      |
| Configuration management                        | ✅        | Ansible (`ansible/playbook.yml` + roles)             |
| Idempotent deployments                          | ✅        | Ansible + `docker compose up -d`                     |
| Automatic deployment from main                  | ✅        | `deploy.yml` gated on workflow_run                   |
| Manual approval gate available                  | ✅        | `environment: production` supports required reviewers |
| Rollback path                                   | ✅        | `terraform apply` + previous git tag + `deploy.yml`  |
| Deployment audit log                            | ✅        | GitHub Actions run history (immutable)               |
| Production secrets out of source                | ✅        | GitHub Secrets → Ansible → `.env` (mode 0640)        |
| No SSH from CI without ephemeral key            | ⚠️         | Currently a long-lived `EC2_SSH_KEY`; OIDC + SSM is the recommended upgrade |

## 13.5 Operate / Monitor

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Metrics collection                              | ✅        | Prometheus + 30 custom counters                      |
| Visualization                                   | ✅        | Grafana                                              |
| Health endpoints                                | ✅        | `/health` + Docker `HEALTHCHECK`                     |
| Container liveness / restart                    | ✅        | `restart: unless-stopped`                            |
| Centralized logging                             | ⚠️         | Logs to stdout (visible via `docker logs`); a real ELK/Loki stack is the next step |
| Alerting                                        | ⚠️         | SOC alerts persisted in DB; Prometheus Alertmanager not wired in |
| Anomaly detection                               | ✅        | SecurityMonitor (auth flood, write burst, multi-vector) |
| Automated incident response                     | ✅        | Auto-quarantine on write burst (ransomware shape)    |

## 13.6 Container & Runtime Security

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Non-root containers                             | ✅        | `USER app:app` backend; `USER 101` frontend          |
| Capability restriction                          | ✅        | `cap_drop: [ALL]`                                    |
| No-new-privileges                               | ✅        | `security_opt: no-new-privileges:true`               |
| Minimal base images                             | ✅        | `python:3.12-slim`, `nginx-unprivileged:alpine`      |
| Read-only mounts where possible                 | ⚠️         | `prometheus.yml` is `:ro`; broader read_only is a follow-up |
| Container healthchecks                          | ✅        | All services                                         |
| Image signature / provenance                    | ❌        | cosign + provenance attestations is the next step    |

## 13.7 Identity & Access

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Authentication                                  | ✅        | JWT (OAuth2 password flow at `/auth/login`)          |
| Authorization (RBAC)                            | ✅        | `require_role("admin" / "employee")`                 |
| Password storage                                | ✅        | bcrypt with `passlib`                                |
| Session management                              | ✅        | Stateless JWT, expiry from settings                  |
| Secret rotation procedure                       | ✅        | GitHub Secret rotation + `deploy.yml` re-run         |

## 13.8 Network Security

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Network segmentation                            | ✅        | Docker bridge `ssms_net` isolates inter-container traffic |
| Firewall at cloud level                         | ✅        | AWS Security Group                                   |
| Firewall at OS level                            | ✅        | UFW configured by Ansible `roles/common`             |
| Ports allow-listed (not deny-listed)            | ✅        | Both SG and UFW default-deny + explicit allow         |
| TLS in transit                                  | ❌        | HTTP only — Caddy + Let's Encrypt is the next step   |
| TLS to DB                                       | ⚠️         | MariaDB-to-app over docker bridge; would need TLS for cross-host |

## 13.9 Supply chain

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| Pinned dependency versions                      | ✅        | `requirements.txt` exact pins                        |
| Automated dependency updates                    | ✅        | Dependabot weekly PRs                                |
| Vulnerability advisories surfaced               | ✅        | Bandit + Semgrep + pip-audit + Trivy SARIF in Security tab |
| Reproducible builds (registry-pulled bases)     | ✅        | Docker Hub `python:3.12-slim`, `mariadb:11`, etc.    |
| Image immutability                              | ✅        | `ssms/backend:latest` rebuilt each pipeline run     |
| Image digest pinning                            | ❌        | Future: pin `@sha256:...` instead of tags            |

## 13.10 Documentation & Process

| Requirement                                     | Satisfied | How                                                  |
|-------------------------------------------------|-----------|------------------------------------------------------|
| README with quick-start                         | ✅        | `README.md`                                          |
| Architecture document                           | ✅        | `docs/02-architecture.md`                            |
| Security document                               | ✅        | `SECURITY.md` + `docs/10-security.md`                |
| Threat model                                    | ✅        | `docs/14-risk-analysis.md`                           |
| Runbook for redeploy                            | ✅        | `docs/12-deployment-flow.md`                         |
| Onboarding doc for a new developer              | ✅        | `docs/00-index.md` + this folder                     |
| Disaster recovery procedure                     | ✅        | "Re-create the EC2 from scratch" in section 12       |

## 13.11 Overall maturity score (self-assessment)

Mapping to the OWASP DSOMM levels (1 = minimum, 4 = best in class):

| Dimension                | Level | Comment                                             |
|--------------------------|-------|-----------------------------------------------------|
| Build & Deployment       | 3     | Reproducible, scanned, automated, gated             |
| Patch & Component        | 3     | Pinned, scanned weekly, auto-PR'd                   |
| Application              | 2-3   | JWT + bcrypt + RBAC + auto-quarantine; no DAST yet |
| Infrastructure           | 3     | IaC + CM + segmentation + hardened containers       |
| Identity & Access        | 2-3   | RBAC + bcrypt + JWT; no MFA / SSO yet               |
| Logging & Monitoring     | 3     | Metrics, anomaly detection, healthchecks; no log aggregation yet |
| Culture & Org            | n/a   | Single-developer demo; would be 2 in a small team   |

That puts the project squarely at **DSOMM Level 2-3 across the board**,
which is roughly "professional-grade security for a small/medium app" —
the sweet spot for a final-year capstone.

> When the actual rubric arrives, each row above can be reanchored to the
> exact wording. The evidence rows (right-hand column) won't change.
