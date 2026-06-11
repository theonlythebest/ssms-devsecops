# SSMS — Smart Store Management System

> Projet de soutenance Bac+3 Cybersécurité & DevSecOps 
> Plateforme complète de gestion de magasin avec **SOC intégré**, **vidéosurveillance comportementale**, **auto-validation cross-source** et **observability Prometheus / Grafana**.

<img width="898" height="438" alt="image" src="https://github.com/user-attachments/assets/e4533eed-8838-4302-9043-b4bda79d1354" />


---

## Le projet

SSMS est un système de gestion de magasin (caisse, stock, commandes web, vidéosurveillance) sur lequel j'ai intégré le **DevSecOps**.

- **Détection comportementale** : YOLOv8 et ByteTrack analysent la posture des personnes (loitering, main vers la poche, fuite rapide) et calculent un score de suspicion.
- **Auto-validation des alertes** : à chaque alerte CCTV, le backend croise avec l'inventaire en base. Si un produit a disparu dans la fenêtre de l'événement, c'est un vrai vol. Sinon, c'est un faux positif. Résultat : **80% des alertes auto-classifiées sans intervention humaine**.
- **SOC Quarantaine** : un middleware FastAPI compte les écritures en base et les échecs d'authentification. Au-delà d'un seuil anormal (pic d'écritures typique d'un ransomware qui aurait compromis l'app, ou brute-force sur les comptes), l'API se met automatiquement en quarantaine et bloque tous les writes. L'opérateur peut la désarmer manuellement depuis le dashboard.
- **Dashboard tactique** + **Grafana SOC** : 16 panels Prometheus pour suivre en temps réel les métriques système, sécurité et métier (revenue, ventes, intrusions CCTV, latence).
- **Pipeline CI/CD** : 5 scanners de sécurité (Bandit, Semgrep, Trivy, Gitleaks, pip-audit) et un déploiement automatique sur AWS via Terraform + Ansible.

---

## La stack

| Couche | Tech |
| --- | --- |
| Backend API | FastAPI, SQLAlchemy, JWT, bcrypt |
| Database | MariaDB 11 + SQLite |
| Frontend | HTML/CSS/JS |
| Vidéosurveillance | YOLOv8-pose + ByteTrack |
| Monitoring | Prometheus + Grafana |
| Conteneurs | Docker Compose |
| Infrastructure | Terraform + Ansible |
| CI/CD | GitHub Actions, Bandit, Semgrep, Trivy, Gitleaks, pip-audit |

---

## Ce que j'ai construit

### 1 ~ Dashboard tactique 

- **Status bar** : `SECURITY: OK / QUARANTINED`, backend DB actif, dernière mise à jour
- **5 KPI cards** : Total Revenue, Expired Products, Low Stock, Web Orders, Anomalies
- **SOC Events feed** scrollable avec sévérité par couleur (critical pulse rouge, warning orange, info cyan)
- **Bandeau d'urgence quarantaine** : si l'anti-ransomware se déclenche, un bandeau rouge clignotant apparaît avec un bouton `RELEASE QUARANTINE` qui désarme en un clic

<img width="1919" height="942" alt="image" src="https://github.com/user-attachments/assets/342ed2a5-033f-476e-9067-da6202f111d0" />
<img width="1919" height="916" alt="image" src="https://github.com/user-attachments/assets/15551fbf-7242-4d66-8562-324985ce6fd3" />
<img width="1919" height="623" alt="image" src="https://github.com/user-attachments/assets/61b939f4-fd3e-4f27-92c4-8309846ad36e" />
---

### 2 ~ CCTV Intelligence Center

**Détection comportementale par YOLOv8-pose + ByteTrack** :

- YOLOv8-pose détecte les personnes ET les 17 keypoints du squelette (épaules, poignets, hanches…)
- ByteTrack maintient un ID persistant par personne pendant ~30 secondes
- Un score de suspicion cumulé monte selon 4 signaux :
  - `+30` loitering en zone critique
  - `+35` accroupissement (geste de dissimulation)
  - `+40` main vers la poche
  - `+25` fuite rapide après événement
- 3 seuils : `WATCH 30-59` / `SUSPECT 60-79` / `ALERT 80+`
- Cooldown 8s pour éviter le spam, rate-limit 1.2s côté worker pour ne pas saturer le SOC

<img width="898" height="448" alt="image" src="https://github.com/user-attachments/assets/5501317b-6a12-424a-ac57-d4798744b027" />

> Par souci de confidentialité, les flux vidéo réels du magasin ne sont pas diffusés dans cette démo. La détection tourne sur une séquence libre de droits : la zone **rouge** délimite la *caisse* (`checkout_area`), la zone **orange** délimite le *stock* (`stock_area`). Le pipeline traite n'importe quel flux RTSP ou MP4 de la même manière.

### 3 ~ Auto-validation par corrélation inventaire

Pour chaque alerte CCTV, le backend interroge `inventory_log` sur une fenêtre `[T−30s, T+5min]` :

- Si une perte stock non expliquée apparaît dans la fenêtre → la caméra dit vrai → **AUTO ✓ TRUE**
- Si aucun mouvement d'inventaire → la caméra s'est trompée → **AUTO ✗ FALSE**
- Si la sévérité est critique mais sans corrélation → **GREY ZONE** (un humain doit faire le choix)

<img width="768" height="494" alt="image" src="https://github.com/user-attachments/assets/7cbc6efe-7699-4149-9bd9-6e21d7f9ae92" />

<img width="898" height="180" alt="image" src="https://github.com/user-attachments/assets/67f8ebcf-22d8-4c54-93cb-891f0cb46bf5" />

> Résultat : **80% des alertes auto-classifiées sans intervention humaine**. 

---

### 4 ~ Quarantaine SOC automatique (anti-ransomware / anti-brute-force)

Un middleware FastAPI qui surveille en continu et déclenche la quarantaine dans 3 scénarios :

- **Pic d'écritures massif** (≥ 80 writes/min par défaut) : pattern typique d'un ransomware qui aurait compromis l'application et tenterait de chiffrer/corrompre la base ou d'une sabotage massif.
- **Brute-force sur l'authentification** (≥ 5 échecs/min par défaut) : quelqu'un qui tente de cracker un compte admin.
- **Multi-vecteurs combinés** : plusieurs signaux suspects détectés simultanément (pattern coordonné).

Quand la quarantaine est active :
- Tous les writes (`POST`, `PUT`, `PATCH`, `DELETE`) sont bloqués avec un **HTTP 503**.
- Une whitelist garde les endpoints critiques accessibles (`/auth/login`, `/cctv/events`, `/security/*`, `/health`) pour que l'opérateur puisse réagir.
- Un compteur Prometheus `quarantine_blocked_requests_total` trace tout ce qui a été bloqué.

<img width="898" height="440" alt="image" src="https://github.com/user-attachments/assets/3f797068-f27b-4c13-8560-2c6d9e9a89fa" />

> L'opérateur SOC peut désarmer manuellement en un clic depuis le bandeau d'urgence du dashboard, ou via `POST /security/quarantine/release` une fois la menace écartée.
---

### 5 ~ Grafana (16 panels)

- **Ligne 1 : Stat cards (6 KPI temps réel)** : Quarantine State (ARMED/QUARANTINE), HTTP req/s, CCTV Intrusions, Auto-classified (5m), Failed Logins, Revenue cumulé
- **Ligne 2 : CCTV intelligence** : Events by Severity (timeseries empilé), Auto-verdict Distribution (donut TP/FP/GREY), CCTV by Zone (bar gauge par caméra)
- **Ligne 3 : Sécurité** : Authentication Events (successful/failed/invalid JWT), SOC Threat Detection (cumul des alertes par sévérité)
- **Ligne 4 : Métier** : Barcode Activity (sells/restocks), Business Throughput (POS sales + web orders)
- **Ligne 5 : Performance** : HTTP Request Rate by Status (2xx/4xx/5xx), System Health Score (gauge 0-100%), Avg Response Time
- **Ligne 6 : SLI latence** : p50 / p95 / p99 en full-width pour traquer les régressions de perf

<img width="898" height="449" alt="image" src="https://github.com/user-attachments/assets/cc0115e3-d63b-4d13-8b81-1a58d3ee6e87" />

> Grafana se configure tout seul au démarrage : la connexion à Prometheus et le dashboard avec ses 16 panels sont chargés automatiquement. 

---

### 6 ~ Shop e-commerce 

Un shop Click & Collect :

- Catalogue produits + filtres par catégorie
- Panier en modal latérale 
- Checkout simulé → génère une commande, un order ID, et incrémente `revenue_total` (visible dans Grafana)
- Scan barcode côté admin pour les opérations sells / restocks

<img width="1867" height="935" alt="Capture d&#39;écran 2026-06-11 164044" src="https://github.com/user-attachments/assets/44d4915b-8596-4545-bd82-4f7282a3196a" />

---

### 7 ~ Pipeline CI/CD security (GitHub Actions)

3 workflows automatiques à chaque push :

- **`ci-security.yml`** — 5 jobs en parallèle
  - **Bandit** → SAST Python (détecte `eval`, `subprocess shell=True`, mots de passe en dur…)
  - **Semgrep** → patterns dangereux selon les règles OWASP Top 10
  - **pip-audit** → CVE connues dans les dépendances Python
  - **Gitleaks** → secrets/tokens commités par erreur (fait un scan complet de l'historique git)
  - **flake8** → style du code (non-bloquant)
- **`docker-build-scan.yml`** — build des images Docker en matrice (backend + frontend, multi-stage, non-root) puis **Trivy** scan CVE sur chaque image + génération **SBOM** au format SPDX. Si une CVE `CRITICAL` est trouvée → pipeline rouge.
- **`deploy.yml`** — si les 2 précédents sont verts ET qu'on est sur `main`, déploiement automatique sur AWS via Ansible. Lançable aussi manuellement.

Tous les rapports sont au format **SARIF** et uploadés vers l'onglet **GitHub Security** du repo → un seul endroit pour voir toutes les failles, avec ligne + colonne du code fautif.

**Dependabot** ouvre une PR de mise à jour 1× / semaine sur les dépendances Python, GitHub Actions et Dockerfiles. Chaque PR passe par toute la pipeline avant d'être mergée.

<img width="707" height="622" alt="image" src="https://github.com/user-attachments/assets/dbe02c18-6a16-4597-8e9c-1b5e43c99c2f" />

> *Pipeline `ci-security` déclenchée par une PR Dependabot (`bump python-multipart 0.0.20 → 0.0.32`). Les 5 jobs (Lint, Bandit, Semgrep, pip-audit, Gitleaks) passent en 58 secondes. Gitleaks confirme : « No leaks detected ».*

<img width="645" height="724" alt="image" src="https://github.com/user-attachments/assets/ab538d49-4a04-4c0e-871d-e30bf2dddb75" />

> *Pipeline `docker-build-scan` sur la même PR Dependabot : Trivy filesystem + IaC, build matrice backend + frontend avec scan CVE, et validation `docker compose config`. 

---

### 8 ~  Infrastructure as Code (Terraform + Ansible)

J'ai écrit le code complet pour déployer toute la stack sur AWS automatiquement. **L'instance n'est pas allumée en permanence** (un serveur AWS qui tourne 24/7 coûte de l'argent), mais le code est validé en CI à chaque push et peut être déployé en 6 minutes quand on en a besoin.

**Comment ça marche, en 2 outils :**

- **Terraform** crée le serveur AWS : la machine, l'adresse IP fixe, le réseau et le pare-feu.
- **Ansible** configure ce qui tourne dessus : installation de Docker, pare-feu local, code du projet, lancement de la stack.

**Pour tout déployer, 2 commandes :**

```bash
terraform apply           # crée la VM 
ansible-playbook playbook.yml  # configure tout 
```

**Sécurité réseau :**

- Frontend (port 80) → public
- API, Grafana, Prometheus, SSH → accès limité à l'IP de l'équipe
- **Double pare-feu** : un côté AWS, un côté serveur, si l'un saute, l'autre tient.

---

## Architecture

<img width="1046" height="922" alt="image" src="https://github.com/user-attachments/assets/b00a3f5a-7db8-4a4a-aae6-618d5daa6abf"/>

---

## Compétences mises en œuvre

- **Cybersécurité** : authentification JWT, RBAC admin/employee, anti-ransomware par middleware custom, GDPR-safe vidéosurveillance (zéro stockage facial), SARIF reporting, CVE scanning, gestion des secrets via `.env`
- **DevOps** : Docker multi-stage non-root, Terraform AWS, Ansible playbook, GitHub Actions, healthchecks Docker, double pare-feu (Security Group + UFW)
- **Backend** : FastAPI async, SQLAlchemy 2.x ORM, Pydantic v2, Prometheus instrumentation, JWT + bcrypt
- **Computer Vision** : YOLOv8-pose detection + 17 keypoints, ByteTrack persistent tracking, scoring comportemental multi-signaux, zones polygonales avec `cv2.pointPolygonTest`
- **Frontend** : Vanilla JS (zéro framework), CSS variables + animations, responsive grids, localStorage pour la persistance des reviews CCTV
- **SRE / Observability** : 20+ métriques Prometheus custom, Grafana auto-provisionné (dashboards JSON versionnés), SLI / SLO basics (p50/p95/p99), gauge System Health Score composite

