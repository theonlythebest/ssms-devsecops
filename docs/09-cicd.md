# 9. CI/CD with GitHub Actions

## 9.1 What is CI/CD?

- **Continuous Integration (CI):** every change is automatically built and
  tested against the rest of the codebase, on every push and pull request.
  The goal is to keep the main branch always in a deployable state.
- **Continuous Delivery (CD):** every change that passes CI is also packaged
  and released somewhere — staging, production, an artifact registry.
- **Continuous Deployment** (a stricter form): every passing change is
  *automatically deployed*, without a human in the loop. This project does
  this, gated on the security workflows succeeding.

**DevSecOps** adds an "S": *security* steps are run as part of CI. SAST,
secret scans, dependency CVEs and container scans must be green before
deployment can happen.

## 9.2 GitHub Actions in 60 seconds

A **workflow** is a YAML file under `.github/workflows/`. It declares:

- **Triggers** (`on:`) — events that fire the workflow: `push`,
  `pull_request`, `workflow_dispatch`, `workflow_run`, schedules.
- **Jobs** — independent units that run in parallel by default.
- **Steps** inside each job — a sequence of `run:` commands or `uses:`
  references to reusable Actions from the marketplace.
- **`runs-on:`** — the GitHub-hosted runner OS (`ubuntu-latest`).
- **`needs:`** — sets up dependencies between jobs.
- **`permissions:`** — what scopes the GITHUB_TOKEN has during this run.

We have three workflows:

```
.github/workflows/
├── ci-security.yml          (lint + SAST + dep CVEs + secret scan)
├── docker-build-scan.yml    (build images, Trivy scans, SBOM)
└── deploy.yml               (Ansible deploy to EC2, gated)
```

Plus `dependabot.yml` (not a workflow — config for the Dependabot service).

## 9.3 `ci-security.yml` — five jobs in parallel

Triggers: `push`, `pull_request`, `workflow_dispatch`.

Permissions:

```yaml
permissions:
  contents: read
  security-events: write    # required to upload SARIF reports
  actions: read
```

The five jobs run concurrently:

### 9.3.1 `lint` — flake8

```yaml
- uses: actions/setup-python@v5
- run: pip install --upgrade pip flake8
- run: flake8 backend/app
```

Style + obvious correctness bugs. Reads `.flake8` for project rules
(line length, ignored codes). A failure is binary: build fails on the
first violation.

### 9.3.2 `bandit` — Python SAST

```yaml
- uses: actions/setup-python@v5
- run: pip install "bandit[sarif]==1.7.10"
- run: bandit -r backend/app -s B311 -f json -o bandit.json
- run: bandit -r backend/app -s B311 -f sarif -o bandit.sarif
- uses: github/codeql-action/upload-sarif@v3
  with: { sarif_file: bandit.sarif, category: bandit }
- uses: actions/upload-artifact@v4
  with: { name: bandit-report, path: bandit.json }
- run: |
    high=$(python -c "import json; ...")
    if [ "$high" != "0" ]; then
      echo "::error::Bandit reported $high HIGH-severity findings"
      exit 1
    fi
```

What Bandit catches:

- `subprocess.run("...", shell=True)` with user input → command injection
- `hashlib.md5` / `sha1` for security purposes → weak crypto
- Hard-coded passwords or `password = "..."` patterns
- `eval()` / `exec()` of user input
- `xml.etree.ElementTree.parse` without secure parser → XXE
- Insecure SSL/TLS configuration

`-s B311` skips the "pseudo-random not suitable for crypto" finding because
we use `random` only for demo seeding.

The job posts SARIF to the **GitHub Security tab** ("Code scanning" view).
That means a teacher or reviewer can click any finding and see the exact
line annotated in the PR.

### 9.3.3 `semgrep` — rules-based SAST

```yaml
container: { image: returntocorp/semgrep:latest }
steps:
  - uses: actions/checkout@v4
  - run: |
      semgrep ci \
        --config p/ci \
        --config p/security-audit \
        --config p/owasp-top-ten \
        --config p/python \
        --config p/dockerfile \
        --sarif --output=semgrep.sarif || true
  - uses: github/codeql-action/upload-sarif@v3
```

Semgrep is **the** open-source rules-based SAST. The community maintains
rule packs (`p/...`) we pull in:

- `p/ci` — "things that should never reach CI".
- `p/security-audit` — broad security rules.
- `p/owasp-top-ten` — the OWASP Top 10 categories.
- `p/python` — Python-specific patterns.
- `p/dockerfile` — Dockerfile anti-patterns.

Semgrep finds things Bandit doesn't (cross-language patterns,
Dockerfile smells, SQLAlchemy-specific gotchas) and vice versa.

### 9.3.4 `pip-audit` — dependency CVEs

```yaml
- run: pip install pip-audit
- run: pip-audit -r backend/requirements.txt --strict --format json --output pip-audit.json
- uses: actions/upload-artifact@v4
```

`pip-audit` cross-references our pinned versions against the **Python
Packaging Advisory Database** (the official PSF-maintained source of
truth for Python CVEs). `--strict` makes it exit non-zero on any
vulnerable dep, which fails the build.

This is the same DB Dependabot uses, just queried at PR time so a CVE
that landed yesterday is caught before merge.

### 9.3.5 `gitleaks` — secrets in git history

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }       # full history, not just HEAD
- uses: gitleaks/gitleaks-action@v2
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    GITLEAKS_ENABLE_SUMMARY: "true"
```

Gitleaks walks every commit in every branch looking for committed
secrets — AWS keys, GitHub tokens, private keys, JWTs, slack webhooks.
`fetch-depth: 0` is essential: without it gitleaks only sees the current
commit and misses anything that was committed-then-removed (still
recoverable from history).

The `.gitleaks.toml` we ship allow-lists known-safe placeholders like
`change-me-in-production` so the documentation doesn't trip the scanner.

## 9.4 `docker-build-scan.yml` — build then scan

Triggers: `push`, `pull_request`, `workflow_dispatch`.

Permissions:

```yaml
permissions:
  contents: read
  security-events: write
```

### 9.4.1 `trivy-fs` — filesystem scan (no build needed)

```yaml
- uses: aquasecurity/trivy-action@0.28.0
  with:
    scan-type: fs
    scan-ref: .
    format: sarif
    output: trivy-fs.sarif
    severity: HIGH,CRITICAL
    ignore-unfixed: true
    scanners: vuln,secret,misconfig
- uses: github/codeql-action/upload-sarif@v3
```

Trivy in `fs` mode scans the working tree for:

- **vuln**: vulnerable language packages picked from lockfiles.
- **secret**: same idea as Gitleaks but Trivy has its own ruleset; two
  scanners catching the same thing is fine — defense in depth.
- **misconfig**: Dockerfile / IaC / Kubernetes manifest anti-patterns.

`ignore-unfixed: true` filters out CVEs with no upstream fix yet — those
are noise we can't act on.

### 9.4.2 `build-scan-image` — matrix per service

```yaml
strategy:
  matrix:
    image:
      - { name: backend,  context: ./backend,  tag: ssms/backend:ci  }
      - { name: frontend, context: ./frontend, tag: ssms/frontend:ci }
steps:
  - uses: docker/setup-buildx-action@v3
  - uses: docker/build-push-action@v6
    with: { context: ..., tags: ..., load: true, cache-from: type=gha, cache-to: ... }
  - uses: aquasecurity/trivy-action@0.28.0       # SARIF for Security tab
  - uses: aquasecurity/trivy-action@0.28.0       # table for log
  - uses: aquasecurity/trivy-action@0.28.0       # exit-code: 1 on CRITICAL
  - uses: aquasecurity/trivy-action@0.28.0       # SBOM SPDX-JSON
  - uses: github/codeql-action/upload-sarif@v3
  - uses: actions/upload-artifact@v4
```

What we build is **identical to what production will run** — same
Dockerfile, same multi-stage, same non-root USER, same tini entrypoint.
The Trivy scan after build sees exactly the bytes that would ship.

Four Trivy invocations on each image because each format / behaviour is
useful:

1. SARIF → uploaded to the Security tab so findings render in the PR view.
2. Table → printed to the job log so a human can read it.
3. Exit-code mode with `severity: CRITICAL` → fails the build on any
   critical CVE (HIGH still passes; HIGH+CRITICAL might be too noisy on
   base images and would block deploys for things we couldn't fix).
4. SBOM mode → emits an SPDX-JSON bill of materials. Useful for "what
   exact `libssl` version is in this image?" audits.

### 9.4.3 `compose-validate`

```yaml
- run: docker compose -f docker-compose.yml config --quiet
```

Parses the compose file and resolves env-substitutions. Catches YAML
typos, missing services, invalid `depends_on` references.

## 9.5 `deploy.yml` — gated Ansible deploy

```yaml
on:
  workflow_run:
    workflows: [ci-security, docker-build-scan]
    types: [completed]
    branches: [main]
  workflow_dispatch:
    inputs:
      branch:   { default: main }
      recreate: { type: boolean, default: false }

jobs:
  deploy:
    if: |
      github.event_name == 'workflow_dispatch'
      || (github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success')
    environment:
      name: production
      url:  "http://${{ secrets.EC2_HOST }}/"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install "ansible-core>=2.16" "ansible-lint>=24"
      - run: ansible-galaxy collection install -r ansible/requirements.yml
      - run: ansible-lint ansible/ || true
      - run: |
          mkdir -p ~/.ssh
          printf '%s\n' "$SSH_KEY" > ~/.ssh/ssms-key.pem
          chmod 600 ~/.ssh/ssms-key.pem
      - run: |
          cat > ansible/inventory.ini << EOF
          [ssms]
          ssms-prod ansible_host=${{ secrets.EC2_HOST }}
          ...
          EOF
      - run: ansible-playbook -i inventory.ini playbook.yml \
             -e ssms_git_branch=${{ inputs.branch || 'main' }} \
             -e ssms_env.JWT_SECRET=${{ secrets.SSMS_JWT_SECRET }} \
             ...
      - run: |
          for url in /health /metrics /; do
            curl -fsS http://${EC2_HOST}:8000$url
          done
```

Gate explained:

- `workflow_run` fires after another workflow finishes — for **any**
  conclusion (success, failure, cancelled). The `if:` predicate filters
  to *only* run on `success`.
- `workflow_dispatch` is the manual "Run workflow" button in the Actions
  tab. It bypasses the gate — useful for emergency redeploys.
- The `environment: production` line is GitHub's "environment protection"
  feature: in Settings → Environments you can require a reviewer to
  approve a deployment before it runs. Free safety net.

Why deploy from a runner via Ansible rather than `terraform apply`-ing
from CI?

- We **don't** want CI to recreate the EC2 every push (that's slow and
  could lose data).
- Ansible is **idempotent**: running it twice in a row is safe. So
  re-deploys are cheap.

## 9.6 Reports + artifacts

Every scan publishes two things:

1. A **SARIF file** (Static Analysis Results Interchange Format) uploaded
   to the GitHub `code-scanning` API. SARIF is the JSON standard for SAST
   findings; GitHub knows how to render it inline on PRs and in the
   Security tab. Multiple uploads from the same workflow are merged.
2. A **JSON artifact** attached to the workflow run, downloadable from
   the run summary page. Useful for offline analysis or compliance docs.

The Security tab thus aggregates findings from **five** sources
(Bandit, Semgrep, pip-audit, Trivy fs, Trivy image × N) into a unified
view.

## 9.7 Dependabot — passive but powerful

`.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/backend"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/backend"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/frontend"
    schedule: { interval: weekly }
  - package-ecosystem: github-actions
    directory: "/"
    schedule: { interval: weekly }
```

Each week, Dependabot scans:

- `backend/requirements.txt` for outdated pinned Python deps.
- `backend/Dockerfile` and `frontend/Dockerfile` for newer base images.
- `.github/workflows/` for action versions to bump.

It opens **one PR per outdated dep**, including the changelog and the
CVE list. Each of those PRs goes through the **same** ci-security +
docker-build-scan workflows. So a Dependabot PR that fixes a CVE has its
own security scan to prove it didn't introduce a worse one.

## 9.8 When pipelines go red

Failure cases and exact symptoms:

| Symptom                                                 | Cause                                              |
|---------------------------------------------------------|----------------------------------------------------|
| `lint` job red, "E501 line too long" annotation         | flake8 violation — fix the formatting              |
| `bandit` job red with "HIGH-severity findings" message  | Bandit found a HIGH issue — read the SARIF in PR   |
| `semgrep` job red                                       | A `p/ci` blocker rule triggered                    |
| `pip-audit` job red                                     | A pinned dep has a CVE — bump the version          |
| `gitleaks` job red                                      | A secret was committed — rotate + amend history    |
| `trivy-fs` job red                                      | Dockerfile / IaC misconfig found                   |
| `build-scan-image` matrix red                           | A CRITICAL CVE in the built image (rebuild against a newer base) |
| `compose-validate` red                                  | docker-compose.yml has a typo                      |
| `deploy` skipped silently                               | One of the gate workflows didn't succeed           |
| `deploy` red on smoke test                              | The EC2 is up but the URL didn't return 200        |

Each failure mode is recoverable with a focused fix. The diagnostic loop
takes minutes, not hours.

## 9.9 Local reproduction

Every CI scan can be reproduced offline in seconds:

```bash
flake8 backend/app
bandit -r backend/app -s B311
semgrep --config p/ci --config p/security-audit --config p/python backend/app
pip-audit -r backend/requirements.txt --strict
docker run --rm -v "$PWD":/scan zricethezav/gitleaks:latest detect --source /scan
docker run --rm -v "$PWD":/scan aquasec/trivy fs --severity HIGH,CRITICAL --ignore-unfixed /scan
docker build -t ssms/backend:dev ./backend
docker run --rm aquasec/trivy image --severity CRITICAL,HIGH --ignore-unfixed ssms/backend:dev
docker compose -f docker-compose.yml config --quiet
```

This is the *single most important* command list for the oral defense:
"I can show you any one of these locally in front of you and it gives the
same answer as CI."
