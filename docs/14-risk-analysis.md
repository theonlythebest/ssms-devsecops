# 14. Risk analysis

## 14.1 Methodology

We use a lightweight **STRIDE × CVSS** approach:

- **STRIDE**: enumerate threats by category (Spoofing, Tampering,
  Repudiation, Information disclosure, Denial of service, Elevation of
  privilege).
- For each threat, score:
  - **Likelihood** (1 = rare, 5 = expected)
  - **Impact** (1 = inconvenience, 5 = company-ending)
  - **Risk** = Likelihood × Impact (1–25)
- Then describe the **current mitigation** and any **residual** gap.

The goal is honest enumeration, not theatre. Risks that are still open
are flagged 🔴.

## 14.2 Risk matrix

| #  | Threat (STRIDE)                                                    | Likelihood | Impact | Risk | Status |
|----|--------------------------------------------------------------------|------------|--------|------|--------|
| 1  | Brute-forced JWT (weak `JWT_SECRET`) — Spoofing                     | 2          | 5      | 10   | 🟡 mitigated |
| 2  | SQL injection via crafted input — Tampering                         | 1          | 5      | 5    | 🟢 mitigated |
| 3  | Stolen `EC2_SSH_KEY` from GitHub Secrets — Spoofing                 | 1          | 5      | 5    | 🟡 mitigated |
| 4  | Long-lived SSH key in CI is reusable if leaked — Spoofing           | 2          | 5      | 10   | 🔴 residual  |
| 5  | RCE in a Python dep with no patch — Tampering / EoP                 | 2          | 5      | 10   | 🟡 mitigated |
| 6  | RCE escalates to host via container escape — EoP                    | 1          | 5      | 5    | 🟡 mitigated |
| 7  | Public Grafana / Prometheus credential bruteforce — Spoofing        | 3          | 3      | 9    | 🔴 residual  |
| 8  | Public DB port 3306 via host firewall misconfig — Info disclosure   | 2          | 5      | 10   | 🟢 mitigated |
| 9  | Plaintext HTTP traffic intercepted — Info disclosure                | 4          | 3      | 12   | 🔴 residual  |
| 10 | Ransomware-style write burst from compromised user — Tampering      | 1          | 5      | 5    | 🟢 mitigated |
| 11 | DoS via `/auth/login` flood — DoS                                   | 3          | 3      | 9    | 🟡 mitigated |
| 12 | XSS in operator dashboard rendering user input — Tampering          | 1          | 4      | 4    | 🟢 mitigated |
| 13 | CSRF on state-changing endpoints — Tampering                        | 1          | 3      | 3    | 🟢 mitigated |
| 14 | Sensitive env-var leakage via `/docs` — Info disclosure             | 1          | 4      | 4    | 🟢 mitigated |
| 15 | Compromised dependency uploads SBOM-poisoned tarball — Tampering    | 1          | 5      | 5    | 🟡 mitigated |
| 16 | Container reads host secret files via misconfigured bind mount      | 1          | 5      | 5    | 🟢 mitigated |
| 17 | DB volume not backed up; ransomware encrypts it — Repudiation       | 2          | 4      | 8    | 🔴 residual  |
| 18 | Single EC2 dies; full outage until rebuild — DoS                    | 2          | 3      | 6    | 🔴 residual  |
| 19 | Logs not aggregated; incident forensics incomplete — Repudiation    | 3          | 3      | 9    | 🔴 residual  |
| 20 | Lack of MFA on Grafana admin — Spoofing                             | 2          | 3      | 6    | 🔴 residual  |

## 14.3 Detail per risk

### 14.3.1 Threats fully mitigated 🟢

**#2 SQL injection.** We use SQLAlchemy ORM exclusively. Parameter binding
is automatic. Bandit + Semgrep also scan for raw `cursor.execute(f"...{var}...")`.
Bandit's `B608` rule would catch a regression instantly.

**#8 Public DB port.** AWS Security Group does **not** allow 3306, UFW
default-denies inbound, even though Docker publishes 3306 on the host. An
attacker on the public internet sees `connection refused`.

**#10 Ransomware-style write burst.** `WRITE_BURST_THRESHOLD` (default 30
writes/min) trips the auto-quarantine path in `SecurityMonitor`. The
backend then rejects every non-whitelisted write with 503 until an
operator manually releases via `/security/quarantine/release`.

**#12 XSS.** Operator dashboards interpolate values with `textContent` and
attribute setters, never `innerHTML` with user content. The codebase is
pure-static frontend with explicit DOM construction.

**#13 CSRF.** Authentication uses bearer JWT in the `Authorization` header,
not cookies. CSRF as classically described doesn't apply.

**#14 Sensitive env-var leakage via `/docs`.** `/docs` only shows the
OpenAPI spec for *route* parameters. Server-side environment is not
exposed; `JWT_SECRET` lives in `os.getenv` only.

**#16 Misconfigured bind mount.** We only bind-mount `./frontend:ro` and
`./monitoring/prometheus.yml:ro`. No host-secret directories are exposed
to containers. Trivy fs scan flags risky bind mounts in CI.

### 14.3.2 Threats partially mitigated 🟡

**#1 Brute-forced JWT.** Mitigation: `JWT_SECRET` is 32+ random bytes
(when generated correctly), HS256 alg. Residual: if a developer pushes
a weak secret, no automated check would notice. Improvement: add a
Bandit/Semgrep rule asserting JWT secrets >= 32 chars before deploy.

**#3 Stolen EC2 SSH key.** Mitigation: it lives in a GitHub Secret
(encrypted, masked in logs). Residual: a malicious workflow added to the
repo could exfiltrate it. Improvement: branch-protection on workflows +
required reviewers on `.github/workflows/*` changes.

**#5 RCE in a Python dep with no patch.** Mitigation: pip-audit weekly +
Dependabot weekly + Trivy image scan. Residual: zero-days between scans.
Improvement: GitHub Advanced Security continuous monitoring + faster
scan cadence.

**#6 Container escape.** Mitigation: non-root user, `cap_drop:[ALL]`,
`no-new-privileges`, slim base. Residual: a Linux kernel CVE that
bypasses capabilities (rare). Improvement: enable AppArmor / SELinux
profiles in compose; pin kernel updates via unattended-upgrades on the
EC2.

**#11 `/auth/login` flood.** Mitigation: `AUTH_FAIL_THRESHOLD` + alert.
Residual: no rate limiting at the proxy layer, so a high-bandwidth
attacker can still create CPU pressure. Improvement: add nginx
`limit_req_zone` + per-IP rate limiting at the proxy.

**#15 Supply chain poisoning.** Mitigation: pinned versions, SBOM,
Trivy + pip-audit. Residual: a malicious version uploaded to PyPI before
pip-audit catches it. Improvement: pin by hash (`--require-hashes` in
pip), use a private artifact repository.

### 14.3.3 Residual risks 🔴 — explicit follow-up roadmap

**#4 Long-lived SSH key in CI.** *Fix:* AWS OIDC federation (GitHub
Actions assumes an IAM role; runner uses AWS SSM Session Manager instead
of SSH). No long-lived secret, key never leaves AWS.

**#7 Public Grafana / Prometheus.** *Fix:* close ports 3000 / 9090 in
the AWS Security Group; only reach them via SSH tunnel or VPN. Or
front Grafana with an OAuth proxy (`oauth2-proxy`) for SSO.

**#9 Plaintext HTTP.** *Fix:* add a Caddy or Nginx + Let's Encrypt
sidecar to the compose; route all traffic through 443; redirect 80→443.
Closes #20 (Grafana MFA) too, since we can put a Caddy auth in front.

**#17 No volume backup.** *Fix:* add a daily cron container that
`mysqldump`s into an S3 bucket; lifecycle-rule old backups.

**#18 Single EC2 dies.** *Fix:* move to an AWS auto-scaling group of 1
behind an ALB. Single instance, but auto-recovered. Or accept the RTO
of ~10 min for the redeploy loop.

**#19 No log aggregation.** *Fix:* add Loki + Promtail (Grafana's log
stack) as a sidecar. Containers' stdout already logs to Docker; Promtail
ships them.

**#20 No MFA on Grafana admin.** *Fix:* put oauth2-proxy in front of
Grafana with Google / GitHub SSO, or use Grafana's built-in OIDC
integration.

## 14.4 Attack scenarios walked end-to-end

### 14.4.1 "Credential stuffing"

> An attacker has a list of leaked email/password pairs from a previous
> data breach. They try them against `/auth/login`.

```
1.   Attacker scripts `curl /auth/login -d 'username=x&password=y'`.
2.   Each failure increments `failed_logins_total` and
     `security_monitor.record_auth_failure()`.
3.   After 6 failures in 60s, AUTH_FAIL_THRESHOLD (default 5) is exceeded.
4.   SecurityMonitor returns an anomaly: "Multiple authentication failures".
5.   MonitoringMiddleware persists an Alert row (severity=warning).
6.   If write traffic also spikes (multi-vector), severity escalates to
     critical and quarantine triggers.
7.   Prometheus scrape sees `auth_flood_alerts_total` increment.
8.   Grafana panel shows the spike; operator gets visual signal.
```

### 14.4.2 "Stolen JWT"

> Attacker XSSes a victim, exfiltrates the JWT from localStorage. (We
> don't have XSS by inspection, but assume the worst.)

```
1.   Attacker uses stolen JWT to call /sales POST as the victim.
2.   JWT signature verifies; sub=victim, role=employee.
3.   The middleware records the request; if the attacker tries 100s of
     writes / min, write-burst threshold trips, quarantine engages.
4.   Even without quarantine, JWT expires (default 60 min). Attacker
     must re-XSS.
5.   Defensive next steps in scope: shorter expiry + refresh tokens;
     bind JWT to client fingerprint.
```

### 14.4.3 "Container compromise via vulnerable dep"

> A new CVE drops in `python-jose`. Attacker exploits before patch lands.

```
1.   Attacker's payload triggers RCE inside the backend container.
2.   Process is uid 10001 (non-root). No /etc/shadow access, no
     /var/lib/docker.sock access (we don't mount it).
3.   `cap_drop: [ALL]` prevents `mount`, raw sockets, ptrace.
4.   `no-new-privileges` prevents setuid escalation.
5.   Attacker tries to lateral to mariadb via the docker network.
     They have JWT_SECRET (env-readable from inside) -> can forge admin
     JWTs.  This is the worst credible outcome.
6.   On the host, ufw still default-denies. The attacker can't open new
     ports outward without breaking out of the container first.
7.   Detection: a barrage of /stock/scan from inside trips the write-burst
     anomaly, quarantine engages, alerts fire.
```

The mitigation chain doesn't stop the initial RCE — but it does cap the
blast radius and surface the incident on Grafana within seconds.

## 14.5 Why the architecture is safer than a naive deployment

A "naive" deployment of the same SSMS app would be:

- Single docker run as root, no compose hardening.
- Postgres / MariaDB in plain text, exposed to internet.
- App keys in the docker image as ENV at build time.
- SSH password auth.
- No CI, no scans, no SBOM.

Compared to that baseline, this project removes or reduces every
high-likelihood × high-impact pair. The risk matrix above lists exactly
what's left and where the planned upgrades go.

## 14.6 Compliance angles (informational)

Even though SSMS isn't a regulated app, the architecture happens to
satisfy several common compliance asks:

- **GDPR** — CCTV events store *zone counts*, not faces / IDs. PII
  exposure is minimized.
- **ISO 27001** A.12.6.1 (technical vulnerability management) — Trivy +
  pip-audit + Dependabot.
- **ISO 27001** A.14.2.5 (secure development) — SAST in CI, peer-review
  via PRs.
- **SOC 2** CC7.1 (system monitoring) — Prometheus + Grafana + alerts.
- **NIST 800-53** SI-7 (software integrity) — SBOM per image; pinned
  versions.

These would each need formal evidence collection, but the controls are
in place.
