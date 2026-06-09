# SSMS DevSecOps - Master Documentation

> **Smart Store Management System** — a hands-on DevSecOps reference project
> covering the whole lifecycle: code → CI/CD → security scans → infrastructure
> as code → configuration management → containerized deployment → monitoring.

This document is split into 16 sections, ordered so a reader who knows nothing
about DevSecOps can start at section 1 and finish ready to defend the project
in an oral exam. Each section is self-contained but cross-references the others.

## Table of Contents

| #  | Section                                                                                       | Purpose                                                |
|----|-----------------------------------------------------------------------------------------------|--------------------------------------------------------|
| 1  | [Global project overview](01-overview.md)                                                     | What SSMS is, why, and the DevSecOps philosophy        |
| 2  | [Full architecture](02-architecture.md)                                                       | All components, diagrams, request lifecycle            |
| 3  | [AWS + Terraform](03-terraform-aws.md)                                                        | Infrastructure-as-Code, EC2, security groups           |
| 4  | [Ansible](04-ansible.md)                                                                      | Configuration management, roles, idempotency           |
| 5  | [Docker + Docker Compose](05-docker.md)                                                       | Containers, multi-stage builds, hardening              |
| 6  | [Backend (FastAPI)](06-backend.md)                                                            | Routers, services, models, JWT, request lifecycle      |
| 7  | [Frontend (Nginx)](07-frontend.md)                                                            | Static site serving, port hardening                    |
| 8  | [Monitoring (Prometheus + Grafana)](08-monitoring.md)                                         | Metrics, scraping, dashboards                          |
| 9  | [CI/CD with GitHub Actions](09-cicd.md)                                                       | Workflows, scan tools, gating                          |
| 10 | [Security model](10-security.md)                                                              | Secrets, OWASP, hardening, least privilege             |
| 11 | [Project URLs](11-urls.md)                                                                    | Every URL exposed by the stack                         |
| 12 | [End-to-end deployment flow](12-deployment-flow.md)                                           | Developer → push → CI → deploy → AWS → monitoring      |
| 13 | [DevSecOps rubric mapping](13-requirements-mapping.md)                                        | Project mapped against a standard DevSecOps rubric     |
| 14 | [Risk analysis](14-risk-analysis.md)                                                          | Threats, mitigations, risk matrix                      |
| 15 | [Oral defense preparation](15-oral-defense.md)                                                | Likely questions, demo scenarios, talking points       |
| 16 | [File-by-file deep-dive](16-file-by-file.md)                                                  | Every important file annotated                         |

## How to read this

- **First-time reader:** start at section 1 and read in order.
- **Quick recap before a presentation:** read sections 1, 2, 12, 15.
- **Defending a specific technical choice:** jump to that section directly.
- **"How does X work end-to-end?"** read section 12 then drill into the relevant component section.

## Quick recap

```
Developer commits code
   │
   ▼
GitHub push
   │
   ▼
GitHub Actions (ci-security.yml + docker-build-scan.yml)
   ├─ flake8 / Bandit / Semgrep / pip-audit / Gitleaks
   ├─ Trivy filesystem + image scans, SBOM
   ├─ Docker build (multi-stage, non-root)
   │
   ▼  workflow_run gate (both green = unlock deploy)
deploy.yml
   │
   ▼  SSH (with secret-stored key)
Ansible playbook on the EC2 (provisioned by Terraform)
   ├─ apt + Docker engine + Compose plugin
   ├─ git pull /opt/ssms
   ├─ render .env from GitHub Secrets
   ├─ docker compose up -d --wait
   ▼
SSMS stack runs:
   nginx :80 ──► FastAPI :8000 ──► MariaDB :3306
                      │
                      └─ Prometheus :9090 scrapes /metrics
                              │
                              └─ Grafana :3000 reads from Prometheus
```
