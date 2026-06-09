# 10. Security model

This section walks through every security control in the project, mapped
to the threat it counters. The structure follows the classic "Confidentiality,
Integrity, Availability" framing where useful, but the practical lens here
is **OWASP Top 10 + least-privilege + defense in depth**.

## 10.1 Secrets management

### 10.1.1 Where secrets live (and where they don't)

Secrets in this project:

| Secret                | Lives in                                                          |
|-----------------------|-------------------------------------------------------------------|
| AWS access keys       | `~/.aws/credentials` on the dev box; **never** in repo            |
| Terraform state       | `terraform.tfstate` (gitignored; encrypted S3 in production)      |
| EC2 SSH private key   | `~/.ssh/ssms-key.pem` locally; `EC2_SSH_KEY` in GitHub Secrets    |
| JWT signing secret    | `SSMS_JWT_SECRET` GitHub Secret → injected via `-e ssms_env.JWT_SECRET` |
| MariaDB user password | `SSMS_DB_PASSWORD` GitHub Secret → injected the same way          |
| MariaDB root password | `SSMS_DB_ROOT_PASSWORD` GitHub Secret                             |
| Grafana admin pwd     | `GF_ADMIN_PASSWORD` GitHub Secret                                  |

Secrets **never** live in:

- The Git repository (enforced by Gitleaks + Trivy fs scan + `.gitignore`).
- A Docker image (enforced by avoiding `ENV FOO=secret` lines).
- A Terraform `.tf` file (enforced by Trivy fs misconfig scan).
- Docker Compose **directly** (every secret comes from `${VAR}` env-var
  substitution, defaults are public-safe placeholders).

### 10.1.2 The trust chain from secret to running container

```
GitHub Secrets               (Settings → Secrets → Actions)
       │
       │  ${{ secrets.SSMS_JWT_SECRET }}
       ▼
deploy.yml job env           (only visible in this workflow run, masked in logs)
       │
       │  ansible-playbook ... -e ssms_env.JWT_SECRET=$JWT_SECRET
       ▼
Ansible variable
       │
       │  template env.j2  ->  /opt/ssms/.env  (mode 0640, owner ubuntu)
       ▼
docker compose reads .env
       │
       │  ${JWT_SECRET}
       ▼
Container env var JWT_SECRET
       │
       │  os.getenv("JWT_SECRET")
       ▼
Settings.JWT_SECRET   →   jwt.encode(payload, secret, algorithm=HS256)
```

At every link, the secret is either:

- Stored encrypted at rest (GitHub Secrets are encrypted with libsodium
  per-repo).
- Passed only to processes that need it (the runner, then the EC2, then
  the backend container).
- Masked in CI logs (GitHub auto-masks anything that came from a Secret).
- File-permission-restricted on disk (`.env` is `0640`).

### 10.1.3 Rotating a compromised secret

If `SSMS_JWT_SECRET` leaks:

1. Generate a new one: `openssl rand -base64 32`.
2. Update the GitHub Secret value.
3. Click "Run workflow" on `deploy.yml`.
4. The new value is rendered into `.env`; Ansible restarts the backend.
5. All existing JWTs are now invalid (different signing key). Users have
   to log in again, which is the desired blast radius.

No file edits, no SSH, no manual server work.

## 10.2 OWASP Top 10 coverage

| OWASP item                            | This project's defense                                              |
|---------------------------------------|---------------------------------------------------------------------|
| A01 Broken Access Control             | `require_role("admin"|"employee")` on protected routes; JWT-only routes for state-changing operations |
| A02 Cryptographic Failures            | bcrypt for passwords (no MD5/SHA1); JWT HS256 with secret from env; no plaintext secrets in repo |
| A03 Injection                         | SQLAlchemy ORM throughout — no string concatenation in SQL. Bandit + Semgrep also scan for raw-SQL patterns |
| A04 Insecure Design                   | Defense in depth: SG + UFW + Docker firewall + container hardening + auto-quarantine |
| A05 Security Misconfiguration         | docker compose hardening flags; Trivy misconfig scan; CI gate on compose validate |
| A06 Vulnerable & Outdated Components  | pip-audit, Trivy image scan, Dependabot PRs every week              |
| A07 Identification & Authn Failures   | JWT + bcrypt + auth-flood detection + auto-quarantine               |
| A08 Software & Data Integrity Failures| SBOM per image (SPDX-JSON); images built in CI, not on prod         |
| A09 Logging & Monitoring Failures     | Prometheus + 30 SOC counters + `alerts` table + auto-quarantine     |
| A10 Server-Side Request Forgery       | Backend never makes outbound requests on behalf of user input — no SSRF surface in this codebase |

## 10.3 Least privilege, layer by layer

Every layer answers "what's the smallest authority needed to do my job?":

| Layer            | Identity / privilege                                            |
|------------------|-----------------------------------------------------------------|
| AWS user         | The Terraform user has narrow IAM (EC2 + SG only)               |
| EC2 instance     | No IAM role attached (zero AWS privileges from the host)         |
| EC2 OS user      | Ansible runs as `ubuntu` (passwordless sudo only via SSH)        |
| Docker daemon    | The only privileged thing in the system                          |
| Docker container | `cap_drop: [ALL]`, `no-new-privileges:true`                      |
| In-container user| uid 10001 (`app`) — backend; uid 101 (`nginx`) — frontend        |
| App layer        | JWT role `employee` for normal users, `admin` only for admin endpoints |

If any one of these is broken, the next layer still contains the blast
radius. That's "defense in depth" applied concretely.

## 10.4 Container hardening — the why behind each flag

| Flag                              | Threat it counters                                                   |
|-----------------------------------|----------------------------------------------------------------------|
| `USER app:app` in Dockerfile      | RCE in the app -> attacker lands as non-root inside the container    |
| `cap_drop: [ALL]`                 | Even with root inside the container, can't `mount`, can't raw-socket |
| `no-new-privileges:true`          | setuid binaries (rare) can't elevate                                  |
| Multi-stage build (no compilers)  | RCE can't invoke gcc to compile new exploit code                     |
| Slim base                         | Fewer libraries -> smaller attack surface                            |
| `:ro` mount on prometheus.yml     | Container can't pivot Prometheus config                              |
| Named volume (not bind mount)     | Container can't read paths on the host outside the volume            |
| Healthcheck + restart policy      | A poisoned container gets recycled, raising attacker's persistence cost |

## 10.5 Network security

```
Internet
   │
   │  AWS Security Group
   │  ┌──────────────────────────────────┐
   │  │ 22, 80, 3000, 9090 -> EC2        │  (ingress allowlist)
   │  │ 8000              -> closed       │  (only via SG = no public 8000)*
   │  └──────────────────────────────────┘
   ▼
EC2 OS
   │
   │  UFW (host firewall)
   │  ┌──────────────────────────────────┐
   │  │ default deny in / allow out      │
   │  │ explicit allow 22 80 8000 9090 3000 │
   │  └──────────────────────────────────┘
   ▼
Docker host
   │
   │  iptables rules (managed by Docker)
   │  │  host:80   -> ssms_net frontend:8080
   │  │  host:8000 -> ssms_net backend:8000
   │  │  host:9090 -> ssms_net prometheus:9090
   │  │  host:3000 -> ssms_net grafana:3000
   ▼
Docker network ssms_net (172.18.0.0/16, isolated bridge)
   │
   │  No NAT outwards needed; everything intra-container
   ▼
Containers
```

\* Note: in the current Terraform we have left port 8000 closed on the AWS
SG (so the FastAPI direct UI is *not* reachable from the internet through
that path), but UFW + Docker do open it on the host network for the
trusted internal subnet. This means an SSH-attached operator can reach
`http://localhost:8000/docs` but the open internet can't.

## 10.6 What's *not* yet locked down

The risk analysis section (14) covers this in detail. Summary:

- **No TLS** — port 80 is HTTP, port 8000 is HTTP. Mitigation: Caddy /
  Nginx + Let's Encrypt sidecar; pinning the EC2 to a DNS name.
- **Grafana / Prometheus exposed to internet** — should be VPN-only.
- **Permissive CORS** — `allow_origins=["*"]` is fine for the demo but
  not for production.
- **SSH from 0.0.0.0/0** — should scope to a bastion.
- **Single instance** — no HA. A real production deployment would use
  an autoscaling group + RDS for the DB.

These are documented gaps with one-paragraph mitigations each, not
secret weaknesses.

## 10.7 Operational security

| Practice                   | Where it's enforced                                                 |
|----------------------------|---------------------------------------------------------------------|
| All access auditable       | `inventory_logs`, `alerts` tables; SARIF history in GitHub          |
| All deployments auditable  | GitHub Actions logs are immutable; `deploy.yml` records who/when    |
| Secret rotation            | GitHub Secret update + re-run `deploy.yml` (no SSH needed)          |
| Disaster recovery          | `terraform apply` rebuilds the EC2; `ansible-playbook` rebuilds the app; named volume `mariadb_data` survives container loss |
| Backup strategy (gap)      | Volume backup not automated yet (documented in section 14)          |
| Incident response          | Auto-quarantine on write-burst; manual release via `/security/quarantine/release` |
