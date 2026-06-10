# SSMS — Smart Store Management System

> Projet de soutenance Bac+3 Cybersécurité · DevSecOps · 2026
> Plateforme complète de gestion de magasin avec **SOC intégré**, **vidéosurveillance comportementale**, **auto-validation cross-source** et **observability Prometheus / Grafana**.

[SCREEN: dashboard global SSMS avec classification bar tactique en haut]

---

## Le projet en 30 secondes

SSMS est un système de gestion de magasin (caisse, stock, commandes web) sur lequel j'ai branché tout l'arsenal **DevSecOps** d'un vrai SOC :

- Une **détection comportementale** par caméra qui ne se contente pas de dire « il y a quelqu'un dans la zone », mais qui scoree la suspicion via les keypoints du squelette (loitering, main vers la poche, fuite rapide).
- Un **moteur d'auto-validation** qui croise les alertes vidéo avec l'inventaire en base de données → si la caméra alerte ET qu'un produit disparaît, c'est un vrai vol. Sinon c'est un faux positif. **80% des alertes auto-classifiées sans humain**.
- Un **SOC middleware** anti-ransomware qui détecte les écritures massives et bascule l'API en quarantaine automatique.
- Un **dashboard tactique militaire** + **Grafana SOC** auto-provisionné avec 16 panels temps réel.
- Un **pipeline CI/CD** avec 5 scanners de sécurité (Bandit, Semgrep, Trivy, Gitleaks, pip-audit) et un déploiement automatique sur AWS via Terraform + Ansible.

---

## La stack

| Couche | Tech |
| --- | --- |
| Backend API | **FastAPI 0.115**, SQLAlchemy 2.x, JWT, bcrypt |
| Database | **MariaDB 11** (production) + fallback SQLite (dev) |
| Frontend | HTML/CSS/JS vanilla, dashboard tactique custom + shop premium |
| Vidéosurveillance | **YOLOv8-pose** + **ByteTrack** (Ultralytics) |
| Monitoring | **Prometheus** + **Grafana** auto-provisionné |
| Conteneurs | Docker Compose, hardening (cap_drop, no-new-privileges, non-root) |
| Infrastructure | Terraform (AWS) + Ansible (provisioning) |
| CI/CD | GitHub Actions — Bandit, Semgrep, Trivy, Gitleaks, pip-audit, Dependabot |

---

## Ce que j'ai construit

### 1 — Dashboard tactique SOC militaire

Inspiré des consoles d'opérations type Genetec / Milestone. Fond noir HUD, fontes monospace, classification bar en haut avec horloge UTC live, marqueurs de coin sur chaque card.

- **Status bar** : `SECURITY: OK / QUARANTINED`, backend DB actif, dernière mise à jour
- **5 KPI cards** : Total Revenue, Expired Products, Low Stock, Web Orders, Anomalies
- **SOC Events feed** scrollable avec sévérité par couleur (critical pulse rouge, warning orange, info cyan)
- **Bandeau d'urgence quarantaine** : si l'anti-ransomware se déclenche, un bandeau rouge clignotant apparaît avec un bouton **RELEASE QUARANTINE** qui désarme en un clic

[SCREEN: dashboard avec bandeau quarantaine rouge clignotant + SOC events critiques]

---

### 2 — CCTV Intelligence Center

Le module le plus complet du projet. **Détection comportementale par YOLOv8-pose + ByteTrack** :

- YOLOv8-pose détecte les personnes ET les 17 keypoints du squelette (épaules, poignets, hanches…)
- ByteTrack maintient un ID persistant par personne pendant ~30 secondes
- Un **score de suspicion cumulé** monte selon 4 signaux :
  - `+30` loitering en zone critique
  - `+35` accroupissement (geste de dissimulation)
  - `+40` main vers la poche
  - `+25` fuite rapide après événement
- 3 seuils : `WATCH 30-59` / `SUSPECT 60-79` / `ALERT 80+`
- Cooldown 8s pour éviter le spam, rate-limit 1.2s côté worker pour ne pas saturer le SOC

[SCREEN: feed caméra avec personnes détectées + skeleton tracking + zones colorées]

[SCREEN: panel Live CCTV Alerts du dashboard avec cartes WATCH/SUSPECT par sévérité]

---

### 3 — Auto-validation par corrélation inventaire

La feature qui impressionne le plus en démo. Pour chaque alerte CCTV, le backend interroge `inventory_log` sur une fenêtre `[T−30s, T+5min]` :

- Si une **perte stock non expliquée** apparaît dans la fenêtre → la caméra dit vrai → **AUTO ✓ TRUE**
- Si aucun mouvement d'inventaire → la caméra s'est trompée → **AUTO ✗ FALSE**
- Si la sévérité est critique mais sans corrélation → **GREY ZONE** (un humain doit trancher)

Résultat : **80% des alertes auto-classifiées sans intervention humaine**. C'est exactement l'approche utilisée par Sensormatic / Tyco Retail Solutions dans la grande distribution.

[SCREEN: panel CCTV avec cartes AUTO ✓ / AUTO ✗ et boutons d'override]

[SCREEN: pie chart Grafana "Auto-verdict Distribution" avec % TRUE / FALSE / GREY]

---

### 4 — Quarantaine anti-ransomware (SOC middleware)

Un middleware FastAPI custom qui surveille en continu les requêtes d'écriture :

- Si le **taux d'écritures par minute** dépasse un seuil (30/min par défaut), le middleware **déclenche la quarantaine** : tous les writes sont bloqués avec HTTP 503.
- Une whitelist permet aux endpoints critiques (`/auth/login`, `/cctv/events`, `/security/*`, `/health`) de rester accessibles.
- Un opérateur SOC peut désarmer manuellement via l'UI (bandeau d'urgence) ou via `POST /security/quarantine/release`.

[SCREEN: dashboard avec bandeau "SOC QUARANTINE ACTIVE" et bouton RELEASE]

---

### 5 — Observability Grafana (16 panels)

Auto-provisionné via `monitoring/grafana/provisioning/` — datasource Prometheus connectée à chaud, dashboard chargé au démarrage. Aucun clic manuel.

- **Ligne 1 — Stat cards** : Quarantine State, HTTP req/s, CCTV Intrusions, Auto-classified (5m), Failed Logins, Revenue
- **Ligne 2 — CCTV intelligence** : Events by Severity (timeseries empilé), Auto-verdict Distribution (donut pie chart), CCTV by Zone (bar gauge)
- **Ligne 3 — Sécurité** : Authentication Events, SOC Threat Detection cumulatif
- **Ligne 4 — Métier** : Barcode Activity, Business Throughput
- **Ligne 5 — Perf** : HTTP Request Rate by Status, System Health Score (gauge 0-100%), Avg Response Time
- **Ligne 6 — SLI** : Latency p50 / p95 / p99 full-width

[SCREEN: Grafana avec 16 panels — pie chart, bar gauge, time series, gauge, stat cards]

---

### 6 — Shop e-commerce premium

Un mini-shop Click & Collect avec design retail premium (hero animé, cartes flottantes, testimonials, newsletter, footer pro) :

- Catalogue produits + filtres par catégorie
- Panier en modal latérale avec calcul taxes 10%
- Checkout simulé → génère une commande, un order ID, et incrémente `revenue_total` (visible dans Grafana)
- Scan barcode côté admin pour les opérations sells / restocks
- Raccourci clavier `⌘+K` / `Ctrl+K` pour focus la search bar

[SCREEN: shop SSMS Market avec hero animé + catalogue + panier modal]

---

### 7 — Pipeline CI/CD security (GitHub Actions)

3 workflows automatiques à chaque push :

- **`ci-security.yml`** : 5 scanners en parallèle
  - **Bandit** → failles dans le code Python (eval, subprocess shell=True…)
  - **Semgrep** → patterns dangereux selon les règles OWASP
  - **pip-audit** → CVE connues dans les dépendances Python
  - **Gitleaks** → secrets/passwords commités par erreur
  - **flake8** → style du code
- **`docker-build-scan.yml`** : build des images Docker (multi-stage, non-root) + **Trivy** CVE scan + génération SBOM. Si une CVE CRITICAL est trouvée → pipeline rouge.
- **`deploy.yml`** : si les 2 précédents sont verts ET qu'on est sur `main`, déploiement automatique sur AWS via Ansible. Lançable aussi à la main.

Tous les rapports sont au format **SARIF** uploadés vers l'onglet **GitHub Security** → visible directement dans le repo.

**Dependabot** met à jour les dépendances 1× / semaine sur Python, GitHub Actions et Dockerfiles.

[SCREEN: GitHub Actions avec les 3 workflows verts + Security tab]

---

### 8 — Infrastructure as Code (AWS)

- **`terraform/`** : VPC, subnet, security group, EC2 t3.medium, Elastic IP, S3 backend pour le state lock
- **`ansible/`** : 3 rôles (`common`, `docker`, `ssms`) qui installent Docker, configurent le pare-feu UFW, clonent le projet et lancent la stack
- Workflow complet : `terraform apply` (crée la VM en 1 min) puis `ansible-playbook playbook.yml` (déploie tout en 5-7 min)
- **Double pare-feu** : Security Group AWS côté réseau + UFW côté OS pour la défense en profondeur

[SCREEN: terraform apply + ansible playbook output]

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser  ←→  FastAPI (8000)  ←→  MariaDB (3306)         │
│                  ↑                                       │
│         camera_worker.py  ─────→  POST /cctv/events      │
│                                                          │
│  Prometheus (9090)  ←scrape─  /metrics                   │
│       ↓                                                  │
│  Grafana (3000)  ─auto-provisioned dashboards            │
└─────────────────────────────────────────────────────────┘
```

[SCREEN: schéma architecture global avec flèches entre composants]

---

## Scénario de démonstration

Scénario en 4 actes pour montrer toute la stack en live à la soutenance :

**Acte 1 — Vie nominale**
Dashboard vert, ventes qui tombent dans le shop, camera_worker qui scanne en arrière-plan.

**Acte 2 — Attaque détectée**
5 mauvais logins consécutifs → SOC log "auth_flood pattern" en CRITICAL → bandeau rouge apparaît → Grafana montre le spike `failed_logins_total`.

**Acte 3 — Vol au stockroom**
Caméra détecte loitering + main-poche sur l'ID #6 → escalade à SUSPECT (score 64) → en parallèle, ajustement stock négatif simulé → l'auto-verdict bascule en **AUTO ✓ TRUE** sous les yeux du jury.

**Acte 4 — Containment**
Opérateur clique RELEASE QUARANTINE → système opérationnel à nouveau → Grafana montre la courbe de réponse qui redescend.

[SCREEN: scénario complet en 4 captures côte à côte]

---

## Structure du projet

```
ssms/
├── backend/                       FastAPI + SQLAlchemy + JWT
│   ├── app/
│   │   ├── main.py                point d'entrée
│   │   ├── core/                  config, db, security
│   │   ├── models/                ORM (User, Sale, Order, CCTVEvent, ...)
│   │   ├── schemas/               Pydantic (in/out)
│   │   ├── routers/               endpoints REST
│   │   ├── services/              business logic
│   │   └── utils/                 monitoring middleware + logger SOC + seed
│   └── Dockerfile                 multi-stage, non-root
│
├── frontend/                      dashboard tactique + shop premium
│   ├── index.html                 SOC dashboard
│   ├── shop.html                  e-commerce
│   ├── scanner.html               page caisse
│   ├── app.js                     polling + render
│   ├── shop.js                    catalogue + panier
│   └── style.css / shop.css       skins militaire + retail
│
├── tools/
│   └── camera_worker/             YOLOv8-pose + ByteTrack + scoring
│       └── camera_worker.py
│
├── monitoring/
│   ├── prometheus.yml             scrape config
│   └── grafana/                   provisioning auto-chargé
│       ├── provisioning/          datasources + dashboards providers
│       └── dashboards/
│           └── ssms-soc-overview.json     16 panels
│
├── terraform/                     VPC + EC2 + SG + Elastic IP + S3 backend
├── ansible/                       3 rôles : common, docker, ssms
├── .github/
│   ├── workflows/                 3 pipelines CI/CD
│   └── dependabot.yml             MAJ auto des dépendances
│
├── docker-compose.yml             orchestration des 5 services
├── README.md                      tu es ici
└── SECURITY.md                    détail des mesures de sécurité
```

---

## Compétences mises en œuvre

- **Cybersécurité** : authentification JWT, RBAC admin/employee, anti-ransomware par middleware custom, GDPR-safe vidéosurveillance (zéro stockage facial), SARIF reporting, CVE scanning, gestion des secrets via `.env`
- **DevOps** : Docker multi-stage non-root, Terraform AWS, Ansible playbook, GitHub Actions, healthchecks Docker, double pare-feu (Security Group + UFW)
- **Backend** : FastAPI async, SQLAlchemy 2.x ORM, Pydantic v2, Prometheus instrumentation, JWT + bcrypt
- **Computer Vision** : YOLOv8-pose detection + 17 keypoints, ByteTrack persistent tracking, scoring comportemental multi-signaux, zones polygonales avec `cv2.pointPolygonTest`
- **Frontend** : Vanilla JS (zéro framework), CSS variables + animations, responsive grids, localStorage pour la persistance des reviews CCTV
- **SRE / Observability** : 20+ métriques Prometheus custom, Grafana auto-provisionné (dashboards JSON versionnés), SLI / SLO basics (p50/p95/p99), gauge System Health Score composite

