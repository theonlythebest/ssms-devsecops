# 12. End-to-end deployment flow

This section is the **single best one to memorize for an oral defense**. It
walks the lifecycle of a change from a developer's keyboard to a metric in
Grafana, with every actor named.

## 12.1 The full picture

```
Developer's laptop                GitHub                              AWS EC2
─────────────────────             ───────────────────────────         ───────────────────────────
1. Edit code
2. git push origin feature/x
                       ──────►   3. Push received on feature/x
                                 4. ci-security.yml fires
                                    - flake8
                                    - Bandit (SARIF -> Security tab)
                                    - Semgrep (SARIF)
                                    - pip-audit
                                    - Gitleaks
                                 5. docker-build-scan.yml fires
                                    - Trivy fs scan (SARIF)
                                    - Buildx build backend image
                                    - Buildx build frontend image
                                    - Trivy image scans (SARIF) + SBOM
                                    - compose config --quiet
                                 6. Both green => PR can merge

7. Open PR -> merge to main
                       ──────►   8. Push to main
                                 9. ci-security re-runs (now on main)
                                10. docker-build-scan re-runs (on main)
                                11. workflow_run event fires from each
                                    of those workflows finishing.
                                12. deploy.yml gate:
                                    if both successful and branch=main
                                    => deploy job runs

                                13. deploy job on a fresh runner:
                                    - checkout repo
                                    - apt install ansible
                                    - mkdir ~/.ssh; write key from EC2_SSH_KEY
                                    - regenerate inventory.ini from EC2_HOST secret
                                    - ansible-playbook ...
                                                                ──►   14. Ansible SSHes in as ubuntu
                                                                      15. wait_for_connection
                                                                      16. wait for dpkg lock
                                                                      17. role:common  -> apt, ufw, packages
                                                                      18. role:docker  -> docker-ce + compose
                                                                      19. role:ssms    -> git pull /opt/ssms
                                                                                          render /opt/ssms/.env
                                                                                          docker compose pull
                                                                                          docker compose up -d --wait
                                                                      20. smoke tests:
                                                                          curl /health, /metrics, /
                                                                      21. ALL GREEN
                                22. runner curls back into EC2:
                                    /health, /metrics, /
                                23. workflow turns green;
                                    GitHub posts "deploy to production"
                                    in the PR / commit timeline

                                                                      24. Inside the EC2:
                                                                          Prometheus scrapes /metrics every 5s
                                                                          Grafana datasource queries Prometheus
                                                                          Operator opens http://EC2:3000 and sees
                                                                          live throughput / latency / SOC counters

Developer browses Security tab,
sees zero open findings.
                                                                      25. End users:
                                                                          GET http://EC2/ -> nginx -> shop UI
                                                                          POST /auth/login -> JWT
                                                                          POST /stock/scan -> business logic +
                                                                                              SecurityMonitor +
                                                                                              Prometheus counters
```

## 12.2 What can stop the train, where

| Stage             | Failure shows up as                                  | Recovery                                         |
|-------------------|------------------------------------------------------|--------------------------------------------------|
| Local lint        | flake8 error                                         | Fix and re-commit                                |
| Bandit            | "HIGH severity findings -> failing the build"        | Refactor the offending pattern                   |
| Semgrep           | `p/ci` blocker triggers                              | Read the rule, decide if false positive          |
| pip-audit         | "vulnerable dependency"                              | Bump `requirements.txt`                          |
| Gitleaks          | "secret detected at <file>:<line>"                   | Rotate the secret and amend history              |
| Trivy fs          | misconfig / secret / vuln >= HIGH                    | Fix the file, or add to `.trivyignore` with justification |
| Buildx build      | Dockerfile error / dep install failed                | Fix Dockerfile or `requirements.txt`             |
| Trivy image       | CRITICAL CVE in built image                          | Bump the base image; sometimes wait for upstream fix |
| compose-validate  | compose YAML invalid                                 | Fix the YAML                                     |
| deploy gate       | Either upstream workflow was red                     | Fix the upstream cause                           |
| wait_for_connection| EC2 not reachable on SSH                            | Check `EC2_HOST` secret, check AWS console       |
| dpkg lock         | cloud-init still running                             | Wait — Ansible already does this                 |
| Docker install    | apt failure                                          | Re-run Ansible (idempotent)                      |
| git pull          | branch name doesn't exist                            | Push the branch / fix `ssms_git_branch`          |
| compose up        | image pull failure                                   | Check Docker Hub status / registry auth          |
| smoke test        | `/health` 503                                        | Ansible already retried 20× 5s; if still down, SSH and look at logs |

## 12.3 Re-deploy without changing code

```
Actions tab -> deploy -> Run workflow -> pick branch + recreate flag -> Run
```

`workflow_dispatch` runs the same job. Useful for:

- Rolling a config change after a secret rotation.
- Recovering from a destroyed compose stack.
- Forcing a rebuild against a freshly-pulled base image.

## 12.4 Re-create the EC2 from scratch

```
$ cd terraform
$ terraform destroy           # tears down the EC2 + SG
$ terraform apply             # new EC2, new public IP
$ terraform output -raw public_ip
13.39.86.185                  # (the new IP)
$ # update EC2_HOST secret in GitHub
$ # click Run workflow on deploy.yml
```

The whole loop is ~10 minutes and produces an identical stack.

## 12.5 Promotion path (if this had stages)

The current setup deploys directly to "production" (single environment).
Adding staging would be a one-file change in `deploy.yml`:

```yaml
strategy:
  matrix:
    env:
      - { name: staging,    host_secret: EC2_HOST_STAGING,    require_review: false }
      - { name: production, host_secret: EC2_HOST_PRODUCTION, require_review: true  }
```

…and pointing each env at its own `EC2_HOST_*` secret. The Ansible
playbook doesn't change at all. This is what makes the IaC + CM split
worth the upfront effort.

## 12.6 The 30-second pitch

If a teacher asks "explain your project in 30 seconds", here is the
script. Memorize it.

> "SSMS is a FastAPI + MariaDB store-management system, deployed to AWS
> EC2 by Terraform and Ansible, fronted by Nginx, observed by Prometheus
> and Grafana. Every commit goes through a GitHub Actions pipeline that
> runs flake8, Bandit, Semgrep, pip-audit, Gitleaks, and Trivy
> filesystem + image scans, then builds the Docker images and produces
> an SBOM. Both scan workflows must succeed before the deploy workflow
> Ansible-pushes to the EC2. Containers run as non-root with dropped
> capabilities and no-new-privileges. The backend has a SOC middleware
> that detects auth-flood, write-burst (ransomware shape), and multi-
> vector attacks, and can automatically quarantine itself. Every layer
> is observable via /metrics."

That covers DevSecOps, IaC, CM, container security, runtime security,
observability, and the SOC angle in eight sentences.
