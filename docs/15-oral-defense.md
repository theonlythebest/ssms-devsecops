# 15. Oral defense preparation

This section is built to be **read out loud** the morning of the
presentation. It contains: a 30-second pitch, a 3-minute pitch, the most
likely questions with professional answers, and three demo scenarios.

## 15.1 Memorize this 30-second pitch

> "SSMS is a FastAPI + MariaDB store-management system deployed to AWS
> EC2 by Terraform and Ansible, fronted by Nginx, observed by Prometheus
> and Grafana. Every commit triggers a GitHub Actions pipeline running
> flake8, Bandit, Semgrep, pip-audit, Gitleaks, and Trivy filesystem +
> image scans, generates an SBOM, and only then unlocks the Ansible
> deploy workflow. Containers run as non-root with dropped capabilities.
> The backend includes a SOC middleware that detects auth-flood,
> write-burst, and multi-vector attacks, and auto-quarantines the API
> on ransomware-like patterns. Every layer is observable via /metrics."

## 15.2 3-minute pitch (the demo script)

1. **Problem framing (20 s).** "The project demonstrates a full
   DevSecOps lifecycle on a single application — code, security gates,
   infrastructure as code, configuration management, hardened
   deployment, and real-time monitoring."
2. **Walk the architecture (40 s).** Show the diagram in
   `docs/02-architecture.md` section 2.1. Name the five containers,
   the two networks, the two firewalls, and which port goes where.
3. **Walk the pipeline (40 s).** Open the GitHub Actions tab. Point at
   the three workflows. Open a recent run. Show: 5 SAST jobs in green,
   then Trivy image scan green, then deploy green. Click into Bandit
   SARIF and show a finding in the Security tab.
4. **Walk the runtime (40 s).** SSH to the EC2 (or just open the URLs):
   - `http://<EC2>:8000/docs` — show the auto-OpenAPI doc.
   - `http://<EC2>:8000/health` — JSON response.
   - `http://<EC2>:8000/metrics` — Prometheus text exposition.
   - `http://<EC2>:9090/targets` — green scrape target.
   - `http://<EC2>:3000/` — Grafana dashboard.
5. **Live security demo (40 s).** Pick one:
   - Curl-loop bad logins → watch `failed_logins_total` tick →
     SecurityMonitor anomaly → operator alert appears.
   - Curl-loop POST `/stock/scan` → write-burst threshold → quarantine
     engages → next request returns 503 → operator calls
     `/security/quarantine/release` to restore service.
6. **Close with the DevSecOps philosophy (20 s).** "Every security
   control is *automated, observable, and idempotent*. A teacher who
   wants to verify any control can either click into the Security tab
   or run a single command from `SECURITY.md` section 5."

## 15.3 Most-likely questions and professional answers

### "Why Docker instead of just running the FastAPI app directly on the EC2?"

> Reproducibility, isolation, and density. The Docker image I push to
> the EC2 is byte-identical to what CI scanned with Trivy. Without
> containers, "works on my machine" would be a real possibility, and I'd
> have to install Python, pin systemd units, manage dependencies on the
> host, etc. With containers all that is one Dockerfile.

### "Why Terraform AND Ansible? Couldn't one tool do both?"

> Each plays to its strength. Terraform's declarative model is great for
> cloud APIs that have idempotent CRUD (security groups, EC2 instances).
> Ansible is great for in-OS configuration (apt, ufw, files). Splitting
> the layers means the EC2 is cattle: I can `terraform destroy` and
> `terraform apply` to rebuild it, then re-run Ansible to repopulate. If
> I tried to do everything in Terraform's `remote-exec` provisioner I'd
> reinvent Ansible badly.

### "What does Bandit catch that Semgrep doesn't, and vice versa?"

> Bandit is Python-AST specific: it reads the AST directly so it sees
> patterns Semgrep's regex-derived matchers might miss — for example
> `subprocess.Popen(["sh","-c", user_input])`. Semgrep is rules-based
> and multi-language, so it catches things like raw SQL string-format
> patterns, Dockerfile smells (`FROM ... AS root`), and OWASP Top 10
> patterns across languages. Running both is cheap and catches more.

### "Why two firewalls?"

> Defense in depth. The AWS Security Group is the first ingress filter
> at the cloud edge. UFW on the EC2 is the second filter — useful if I
> ever publish a port from a container that I forgot to also allow at
> the SG. They overlap on purpose; if I misconfigure one, the other
> still protects me.

### "Why `cap_drop: [ALL]`? Doesn't that break things?"

> The backend container doesn't need raw sockets, mount, ptrace,
> set-time, or any other Linux capability. The runtime is just Python
> reading sockets opened for it by uvicorn. Dropping all capabilities
> means even a root-equivalent process inside the container can't do
> anything dangerous. Nothing breaks because nothing relied on
> capabilities in the first place.

### "Show me where the secret lives across the system."

> 1. `JWT_SECRET` is a GitHub Repository Secret, encrypted at rest with
>    libsodium.
> 2. `deploy.yml` references it as `${{ secrets.SSMS_JWT_SECRET }}` only
>    inside the runner job; it's never exposed as an env var to the runner
>    shell.
> 3. The job passes it to `ansible-playbook -e
>    ssms_env.JWT_SECRET=...`. Ansible renders the `.env` template into
>    `/opt/ssms/.env` with mode `0640`.
> 4. `docker compose` reads `.env` at parse time, injects `JWT_SECRET`
>    into the container as an env var.
> 5. The backend reads `os.getenv("JWT_SECRET")` in `Settings.__init__`.
> 6. `jose.jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")`
>    uses it to sign tokens.
> At no point does the value land in source, in a docker image layer, or
> in CI logs (GitHub masks it).

### "How would you rotate that secret?"

> 1. Generate a new value: `openssl rand -base64 32`.
> 2. Update the GitHub Secret.
> 3. Click "Run workflow" on deploy.yml.
> 4. The new value is rendered into `.env`; backend container restarts.
> 5. All existing JWTs become invalid (different signing key). Users have
>    to log in again — exactly the blast radius I want for a rotation.

### "Why MariaDB and not Postgres?"

> The project was originally Postgres + SQLite fallback. I migrated to
> MariaDB because (a) it's slightly easier to back up with `mysqldump`
> for the demo, (b) it has a smaller default image, and (c) the
> `pymysql` driver is pure-Python so the backend image can stay slim and
> not need `libpq`. The SQLAlchemy abstraction means switching back to
> Postgres would be a one-line change in `DATABASE_URL`.

### "What's the multi-stage Docker build buying you?"

> The build stage installs `gcc`, `build-essential`, and `libffi-dev`
> to compile the `cryptography` and `bcrypt` wheels. The runtime stage
> copies only the resolved virtualenv. The shipped image has **no
> compilers**, **no header files**, and **no apt build chain**, which
> drops both the image size and the CVE count Trivy reports. It also
> means if the app is RCE'd, the attacker can't use `gcc` to build new
> tools inside the container.

### "Show me a CRITICAL finding being blocked."

> Open Actions → docker-build-scan → matrix backend → "Trivy image scan
> (fail on CRITICAL)" step. If any CVE has severity=CRITICAL and a known
> fix, exit-code=1 and the job is red. The deploy.yml `workflow_run`
> gate then refuses to dispatch. The fix is to either bump the base
> image to a patched version, or add the CVE to `.trivyignore` with a
> dated justification (which is a process control, not a hack).

### "Tini? Why?"

> Linux gives PID 1 special responsibilities: forwarding signals to
> children and reaping zombie processes. Python isn't built for that.
> If `docker stop` sends SIGTERM and Python is PID 1, the signal goes
> nowhere and Docker waits up to 30 seconds before SIGKILL. Tini is a
> ~12 KB init binary that takes PID 1, forwards signals immediately to
> uvicorn, and reaps zombies. Clean shutdowns are now sub-second.

### "What about TLS?"

> Currently the stack is HTTP-only — documented as risk #9. The
> production upgrade is a 30-line Caddy block that adds Caddy as the
> reverse proxy, terminates Let's Encrypt automatically, and routes
> `/api/*` to the backend. The frontend, Grafana, and Prometheus go
> behind it too. That change is the single highest-value next step.

### "How does Prometheus actually find the backend?"

> Inside the docker network `ssms_net`, Docker's embedded DNS resolves
> service names to container IPs. Prometheus's scrape config says
> `targets: [backend:8000]`. When Prometheus tries to connect, its DNS
> resolver returns the bridge IP of the `ssms_backend` container.
> Nothing about that path goes through the AWS Security Group; the
> traffic is all on the docker bridge.

### "What happens if a Dependabot PR introduces a regression?"

> The PR runs through the same ci-security + docker-build-scan
> workflows. If the new version trips Bandit/Semgrep/Trivy/pip-audit,
> the PR's CI is red and merge is blocked. Branch protection rules can
> require both workflows green before any merge, including Dependabot's.

### "Why is the deploy gated on workflow_run instead of needs:?"

> `needs:` only works between jobs **within the same workflow**.
> Splitting CI security from the docker build into separate workflows
> lets them run independently in parallel and gives clearer failure
> attribution. The `workflow_run` event glues them: deploy.yml fires
> when *either* upstream workflow finishes, and the `if:` predicate
> filters to *only* run when both succeeded. It's the right primitive
> for this gating pattern.

### "How is the EC2 redeployed if it dies?"

> 1. `cd terraform && terraform apply` — recreates the EC2 + SG. New
>    IP.
> 2. Update the `EC2_HOST` GitHub Secret.
> 3. Click "Run workflow" on deploy.yml.
> 4. Ansible runs from scratch, ~7 minutes to a healthy stack.
> The mariadb data is the only thing not preserved — that's documented
> as residual risk #17 with the backup-to-S3 mitigation.

## 15.4 Live demo scripts

### Demo 1 — "Show the security tab"

1. Open the repo on github.com.
2. Click **Security** → **Code scanning**.
3. Filter by tool: Bandit, then Semgrep, then Trivy.
4. Show that the project has zero open findings.
5. Click into any closed finding to show the full SARIF detail (rule
   ID, line annotation, fix suggestion).

### Demo 2 — "Trigger the auto-quarantine"

```bash
# from a workstation
JWT=$(curl -s -X POST http://<EC2>:8000/auth/login \
       -d 'username=admin&password=admin123' | jq -r .access_token)

# Hammer the API
for i in $(seq 1 50); do
  curl -s -X POST http://<EC2>:8000/stock/scan \
       -H "Authorization: Bearer $JWT" \
       -d '{"barcode":"2000000000017","action":"sell"}' &
done
wait

# Within ~30 seconds:
curl http://<EC2>:8000/security/status
#  -> { "quarantined": true, "reason": "Ransomware indicators (write-burst)" }

curl http://<EC2>:8000/sales -X POST ...
#  -> 503 "Service isolated due to security anomaly."

# Release
curl -X POST http://<EC2>:8000/security/quarantine/release \
     -H "Authorization: Bearer $JWT"
```

Open Grafana side by side; the `quarantine_state` gauge goes 0 → 1 → 0.

### Demo 3 — "Push a 'bad' change and watch CI red"

1. On a feature branch, add an obvious Bandit-trip:
   `subprocess.run(user_input, shell=True)`.
2. Push.
3. Open the PR. CI security workflow goes red within 60 seconds.
4. Click into the failed `bandit` job; the SARIF report inlines the
   exact line.
5. Revert the change; CI goes green; PR is mergeable.

This is the cheapest, most convincing demonstration of "the pipeline
catches things".

## 15.5 Trick / tougher questions to prepare for

- **"What's the worst thing that could happen to your stack today?"**
  Honest answer: a kernel-level container escape combined with an
  attacker who already has a JWT. They could read the env-var
  `JWT_SECRET` from inside the container and forge admin tokens. The
  network-level controls would still contain them inside the docker
  bridge; the SOC layer would surface the anomaly.

- **"You have no DAST. Why?"** Out of scope for the demo, but OWASP ZAP
  could be added in a third workflow that spins up the stack with
  `docker compose up -d` and runs an authenticated active scan.

- **"What's *your* role in this project?"** Be honest: "I designed it,
  picked the tools, wrote the code, wrote the Dockerfiles, wrote the
  pipelines, wrote the Ansible roles, wrote the docs. I used AI
  assistance as I would use Stack Overflow — to draft and to challenge
  my reasoning — but every line landed in the repo because I read it
  and understood it."

- **"How would you prove this isn't just security theatre?"** Pick any
  control. Demonstrate it failing on purpose, then passing. Bandit
  example in Demo 3 takes 2 minutes.

- **"What did you find hardest?"** Truthful answers carry: "Getting the
  multi-stage Docker build right while keeping pinned wheels installable",
  or "Tuning the SecurityMonitor thresholds so they don't false-alarm
  on the seeded demo data".

## 15.6 What to have open in tabs during the defense

1. The repo on github.com → Security tab.
2. The most recent successful run of `deploy.yml`.
3. `http://<EC2>:8000/docs` — the Swagger UI.
4. `http://<EC2>:9090/targets` — Prometheus targets up.
5. `http://<EC2>:3000/` — Grafana logged in.
6. A terminal SSH'd to the EC2 with `docker compose ps` ready to show
   five "healthy" containers.
7. This `docs/` folder open in an editor for quick reference.

That's the whole defense. The cards above answer every reasonable
question and a few unreasonable ones.
