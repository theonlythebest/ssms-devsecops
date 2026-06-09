# Sécurité

Ce fichier décrit ce que j'ai mis en place pour protéger le projet. L'idée
DevSecOps c'est de **ne pas attendre la fin du projet pour penser à la
sécurité** : tout est testé automatiquement à chaque commit.

## 1. Le code

### Comment je protège le code lui-même

À chaque `git push`, GitHub lance 5 scanners en parallèle :

| Scanner | Cherche quoi |
|---|---|
| **Bandit** | failles classiques en Python (mot de passe en dur, MD5, eval...) |
| **Semgrep** | patterns dangereux selon les règles OWASP Top 10 |
| **pip-audit** | dépendances Python avec des CVE connues |
| **Gitleaks** | secrets commités par erreur dans l'historique git |
| **Trivy** | failles dans les images Docker |

Si un scanner trouve un problème **grave** (HIGH ou CRITICAL), le pipeline
devient rouge et bloque le déploiement. Les résultats remontent dans
l'onglet **Security** de GitHub où on peut cliquer pour voir la ligne exacte.

### Lancer les scans en local

Si tu veux tester avant de push :

```
pip install bandit semgrep pip-audit flake8
flake8 backend/app
bandit -r backend/app -s B311
pip-audit -r backend/requirements.txt
semgrep --config p/ci --config p/owasp-top-ten backend/app

docker run --rm -v "$PWD":/scan aquasec/trivy fs --severity HIGH,CRITICAL /scan
docker run --rm -v "$PWD":/scan zricethezav/gitleaks:latest detect --source /scan
```

## 2. Les conteneurs Docker

Chaque conteneur a plusieurs couches de protection :

- **Utilisateur non-root** : le backend tourne en uid 10001, nginx en uid
  101. Même si l'application est piratée, l'attaquant n'a pas root.
- **cap_drop: ALL** : on retire toutes les capabilities Linux. Pas de
  possibilité de monter un disque, de faire des raw sockets, etc.
- **no-new-privileges: true** : impossible de gagner des droits via setuid.
- **Multi-stage build** : l'image finale ne contient pas de compilateur ni
  d'outils de dev.
- **Healthchecks** : Docker vérifie que chaque service répond bien.

Tout ça est défini dans `docker-compose.yml` et les `Dockerfile`.

## 3. Le réseau

Il y a **deux pare-feux** qui filtrent les connexions :

- **AWS Security Group** : seuls les ports 22 (SSH), 80 (web), 3000
  (Grafana), 9090 (Prometheus) sont ouverts depuis Internet.
- **UFW sur l'OS** : même filtrage, en deuxième ligne au cas où le SG est
  mal configuré.

À l'intérieur de la VM, les conteneurs sont sur un **réseau Docker isolé**
(`ssms_net`). Ils se parlent entre eux mais rien d'extérieur ne peut les
joindre directement.

## 4. Les secrets

Aucun mot de passe n'est dans le code. Tout passe par des variables :

- En **local** : un fichier `.env` à la racine (gitignored, ne sera jamais
  commité). Le template `.env.example` montre les variables attendues.
- En **CI/CD** : les secrets de GitHub Actions
  (Settings -> Secrets and variables -> Actions).
- Au **runtime** : Docker Compose injecte les variables dans les conteneurs.

Pour générer un secret solide :

```
openssl rand -base64 32
```

## 5. Le runtime (l'application en marche)

Le backend a un **middleware de sécurité** (`MonitoringMiddleware`) qui
analyse chaque requête. Il détecte :

- **Flood de requêtes** (attaque DoS).
- **Burst d'écritures en base** (signature ransomware).
- **Échecs de connexion répétés** (brute force).
- **Attaque multi-vecteur** quand plusieurs signaux montent en même temps.

Si une attaque type ransomware est détectée, le système se met en
**quarantaine automatique** : toutes les écritures sont refusées (503)
jusqu'à ce qu'un admin appelle `POST /security/quarantine/release`.

Toutes ces détections sont aussi visibles dans Grafana via des compteurs
Prometheus (`failed_logins_total`, `quarantine_state`, etc.).

## 6. Détection physique (caméra)

Le script `tools/camera_worker/camera_worker.py` tourne en dehors du stack.
Il utilise YOLOv8 pour détecter les personnes dans une vidéo. Si quelqu'un
entre dans une zone interdite définie (la porte de la réserve par exemple),
il envoie un POST `/cctv/events` au backend. L'alerte apparaît dans le
dashboard quelques secondes plus tard.

## 7. Si tu veux déployer sur AWS

Tu dois configurer ces secrets dans GitHub (Settings -> Secrets) avant que
le workflow `deploy.yml` puisse marcher :

| Secret | À quoi ça sert |
|---|---|
| `EC2_HOST` | l'IP publique de la VM |
| `EC2_SSH_USER` | `ubuntu` en général |
| `EC2_SSH_KEY` | le contenu de la clé `.pem` |
| `SSMS_JWT_SECRET` | la clé pour signer les tokens JWT |
| `SSMS_DB_PASSWORD` | mot de passe user MariaDB |
| `SSMS_DB_ROOT_PASSWORD` | mot de passe root MariaDB |
| `GF_ADMIN_PASSWORD` | mot de passe admin Grafana |



