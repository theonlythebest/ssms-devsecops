# SSMS - Smart Store Management System

Projet de fin d'études (Bac+3 Cybersécurité).

C'est une petite application de gestion de magasin (caisse, stock, commandes
web, surveillance par caméra), et autour de cette application j'ai mis en
place toute la chaîne DevSecOps : tests de sécurité automatisés, déploiement
automatique sur AWS, monitoring temps réel.

## Sommaire

1. [Ce que fait le projet](#1-ce-que-fait-le-projet)
2. [Les outils utilisés](#2-les-outils-utilisés)
3. [Comment les outils se parlent](#3-comment-les-outils-se-parlent)
4. [Lancer le projet sur ta machine](#4-lancer-le-projet-sur-ta-machine)
5. [Les URLs disponibles](#5-les-urls-disponibles)
6. [Comment déployer sur AWS](#6-comment-déployer-sur-aws)
7. [Le pipeline CI/CD](#7-le-pipeline-cicd)
8. [Sécurité](#8-sécurité)
9. [Structure des dossiers](#9-structure-des-dossiers)

---

## 1. Ce que fait le projet

C'est un magasin avec :

- une caisse pour enregistrer les ventes
- un stock avec codes-barres (EAN-13) et dates de péremption
- un site web pour les commandes click-and-collect
- une surveillance par caméra qui détecte si quelqu'un entre dans une zone
  interdite (genre la réserve)

Il y a deux rôles : `admin` et `employee`. La connexion se fait avec un
JWT (un token qu'on garde en mémoire dans le navigateur).

L'idée n'est pas que l'application soit révolutionnaire, c'est de montrer
qu'on sait construire toute l'infrastructure DevSecOps autour.

---

## 2. Les outils utilisés

| Outil | Sert à quoi |
|---|---|
| **FastAPI** | framework Python pour le backend (les routes de l'API) |
| **MariaDB** | la base de données |
| **Nginx** | serveur web qui sert les pages HTML/CSS/JS |
| **Docker + Compose** | pour mettre chaque service dans son conteneur |
| **Prometheus** | collecte les métriques toutes les 5 secondes |
| **Grafana** | affiche les métriques en graphiques |
| **Terraform** | crée la machine virtuelle AWS automatiquement |
| **Ansible** | installe et configure ce qu'il faut sur la VM |
| **GitHub Actions** | lance des tests de sécurité à chaque commit |
| **Bandit / Semgrep / Trivy / Gitleaks / pip-audit** | les 5 scanners de sécurité |
| **YOLOv8 + OpenCV** | détection de personnes dans la vidéo de surveillance |

---

## 3. Comment les outils se parlent

```
   Toi (developpeur)
        |
        | git push
        v
+---------------------+
|   GitHub            |
+---------------------+
        |
        v
+---------------------+
|  GitHub Actions     |   lance les 5 scanners de securite
+---------------------+
        |
        v   (si tout est vert)
+---------------------+
|  Ansible (SSH)      |   se connecte a l'EC2
+---------------------+
        |
        v
+---------------------+
|  AWS EC2 (Ubuntu)   |
|                     |
|  docker compose up  |
|                     |
|  +---------------+  |
|  | nginx :80     |  |
|  +-------+-------+  |
|          |          |
|          v          |
|  +---------------+  |
|  | FastAPI :8000 |  |
|  +-+-----+-----+-+  |
|    |     |     |    |
|    v     v     v    |
|  +---+ +---+ +---+  |
|  |DB | |Pro| |Grf|  |
|  +---+ +---+ +---+  |
+---------------------+
        ^
        |
        |  camera_worker.py (sur ton PC)
        |  envoie les alertes d'intrusion
        |  via POST /cctv/events
```

En une phrase : *tu push -> GitHub teste -> Ansible déploie -> les conteneurs
tournent et se parlent entre eux, ton script caméra envoie ses alertes au
backend depuis l'extérieur*.

---

## 4. Lancer le projet sur ta machine

### Étape 1 - Installer Docker Desktop

Va sur https://www.docker.com/products/docker-desktop/ et installe-le. C'est
gratuit. Lance Docker Desktop après installation, il faut que la baleine soit
verte en bas.

### Étape 2 - Cloner le projet

Ouvre un terminal (PowerShell sur Windows, Terminal sur Mac/Linux) :

```
git clone https://github.com/theonlythebest/ssms-devsecops.git
cd ssms-devsecops
```

### Étape 3 - Créer ton fichier .env

C'est le fichier qui contient les mots de passe (locaux, pas grave si tu mets
des trucs simples) :

```
cp .env.example .env
```

Sur Windows : `copy .env.example .env`

Tu peux ouvrir `.env` avec n'importe quel éditeur pour mettre tes vraies
valeurs si tu veux. Sinon les valeurs par défaut suffisent pour le local.

### Étape 4 - Démarrer

```
docker compose up -d --build
```

`-d` veut dire en arrière-plan (detached).
`--build` veut dire reconstruit les images Docker.

Au premier lancement ça prend quelques minutes (Docker télécharge MariaDB,
Prometheus, Grafana...).

### Étape 5 - Vérifier que tout tourne

```
docker compose ps
```

Tu dois voir 5 lignes "Up X seconds (healthy)". Si une ligne dit "unhealthy"
ou "exited", regarde les logs avec :

```
docker compose logs backend
docker compose logs mariadb
```

### Étape 6 - Ouvrir dans le navigateur

Va sur **http://localhost/** dans Chrome ou Firefox. Tu dois voir le
dashboard.

### Étape 7 - Se connecter

Le projet crée tout seul deux utilisateurs au démarrage :

- **admin** / **admin123** -> peut tout faire
- **employee** / **employee123** -> peut scanner des codes-barres

### Pour tout arrêter

```
docker compose down
```

Pour tout supprimer (y compris la base de données) :

```
docker compose down -v
```

---

## 5. Les URLs disponibles

Une fois que `docker compose ps` montre 5 services healthy :

| URL | Ce que c'est |
|---|---|
| http://localhost/ | Le dashboard principal |
| http://localhost:8000/docs | La documentation auto-générée de l'API |
| http://localhost:8000/health | Check de santé (renvoie un JSON simple) |
| http://localhost:8000/metrics | Les métriques brutes (format Prometheus) |
| http://localhost:9090/ | Prometheus - tu peux faire des requêtes |
| http://localhost:9090/targets | Pour voir que Prometheus capture bien le backend |
| http://localhost:3000/ | Grafana - login admin / la valeur de GF_ADMIN_PASSWORD |

L'URL la plus utile pour la démo : **http://localhost:8000/docs**. Tu peux
tester toutes les routes de l'API depuis le navigateur, sans coder.

---

## 6. Comment déployer sur AWS

### Étape 1 - Avoir un compte AWS et tes clés

Il faut configurer `~/.aws/credentials` avec ton access key et secret.
Si tu débutes : https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html

### Étape 2 - Créer la machine virtuelle avec Terraform

```
cd terraform
terraform init
terraform apply
```

Ça te demandera de taper `yes`. Au bout d'une minute la VM est créée. Note
l'IP publique affichée à la fin (ou récupère-la avec
`terraform output -raw public_ip`).

### Étape 3 - Configurer la VM avec Ansible

Tu as besoin d'avoir la clé SSH `ssms-key.pem` dans `~/.ssh/` et de modifier
`ansible/inventory.ini` pour y mettre la bonne IP.

```
cd ../ansible
ansible-galaxy collection install -r requirements.yml
chmod 600 ~/.ssh/ssms-key.pem
ansible-playbook -i inventory.ini playbook.yml
```

Ansible va :

1. Se connecter à la VM en SSH
2. Installer Docker
3. Configurer le pare-feu UFW
4. Cloner le projet dans `/opt/ssms`
5. Lancer `docker compose up -d`
6. Tester que les URLs répondent

Au bout de 5-7 minutes c'est en ligne. Ouvre `http://<IP-publique>/` dans
ton navigateur.

### Pour tout détruire

```
cd terraform
terraform destroy
```

---

## 7. Le pipeline CI/CD

À chaque `git push` sur GitHub, 3 workflows se déclenchent :

### ci-security.yml

Lance 5 scanners de sécurité en parallèle :

- **Bandit** -> cherche des failles dans le code Python
- **Semgrep** -> cherche des patterns dangereux selon les règles OWASP
- **pip-audit** -> vérifie qu'aucune dépendance n'a de CVE connue
- **Gitleaks** -> cherche si des mots de passe ont été commités par erreur
- **flake8** -> vérifie le style du code

Si un scanner trouve quelque chose de grave, le pipeline passe rouge.

### docker-build-scan.yml

- Construit les images Docker.
- **Trivy** scanne chaque image. Si une CVE CRITIQUE est trouvée -> rouge.
- Génère un SBOM (la liste de tous les composants dans l'image).

### deploy.yml

Si les 2 workflows précédents sont verts ET qu'on est sur la branche `main`,
ce workflow se lance tout seul. Il fait exactement la même chose qu'Ansible
en local mais depuis GitHub.

Tu peux aussi le lancer à la main avec le bouton "Run workflow".

### Voir les résultats

Sur GitHub :

- Onglet **Actions** -> voir les workflows
- Onglet **Security** -> voir les failles trouvées (cliquer pour le détail)

---

## 8. Sécurité

Pour le détail complet, voir [SECURITY.md](SECURITY.md). En 30 secondes :

- Les conteneurs tournent **sans être root** (uid 10001 pour le backend).
- Toutes les **capabilities Linux** sont retirées (cap_drop ALL).
- Les **secrets sont dans .env** (gitignored), jamais dans le code.
- 5 **scanners de sécurité** automatisés à chaque commit.
- 2 **pare-feux** : un côté AWS (Security Group), un côté OS (UFW).
- Un **middleware SOC** dans le backend qui détecte les attaques en temps
  réel et met l'API en quarantaine automatiquement si ça ressemble à du
  ransomware.

---

## 9. Structure des dossiers

```
.
|-- backend/                       le code FastAPI
|   |-- app/
|   |   |-- main.py                point d'entree
|   |   |-- core/                  config, db, securite
|   |   |-- models/                tables SQL (SQLAlchemy)
|   |   |-- schemas/               formats d'entree/sortie (Pydantic)
|   |   |-- routers/               les routes HTTP
|   |   |-- services/              logique metier
|   |   `-- utils/                 logger, middleware SOC, seed
|   |-- Dockerfile                 build multi-stage non-root
|   `-- requirements.txt
|
|-- frontend/                      les pages HTML/JS
|   |-- index.html                 dashboard principal
|   |-- shop.html                  page de commande
|   |-- scanner.html               page caisse
|   `-- Dockerfile                 nginx non-root
|
|-- monitoring/
|   `-- prometheus.yml             config des metriques
|
|-- terraform/                     creation de l'EC2 AWS
|   |-- main.tf
|   |-- outputs.tf
|   `-- provider.tf
|
|-- ansible/                       provisionnement de l'EC2
|   |-- playbook.yml
|   |-- inventory.ini
|   `-- roles/
|       |-- common/                paquets de base + UFW
|       |-- docker/                installation Docker
|       `-- ssms/                  clone repo + docker compose up
|
|-- tools/
|   `-- camera_worker/
|       `-- camera_worker.py       YOLOv8 + envoi des alertes au backend
|
|-- .github/
|   |-- workflows/                 les 3 pipelines CI/CD
|   `-- dependabot.yml             MAJ automatique des dependances
|
|-- docker-compose.yml             orchestration des 5 services
|-- .env.example                   template des variables
|-- README.md                      tu es ici
`-- SECURITY.md                    detail des mesures de securite
```

---

## Auteur

Sarran - projet de fin de cycle, Bac+3 Cybersécurité, 2026.
