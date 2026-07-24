# 🚀 Get Started — ALSABA Backend

Guide de démarrage rapide pour lancer le backend **en local** avec Docker.

---

## 1. Prérequis

- **Docker Desktop** installé et **démarré** (l'icône baleine doit être verte).
- **Git** (pour cloner / mettre à jour le projet).

Vérifier que Docker répond :

```bash
docker info
```

---

## 2. Configuration `.env`

Le fichier `.env` à la racine est **déjà configuré pour localhost** (`DEBUG=True`) avec une `SECRET_KEY` générée.

Variables **obligatoires** (déjà remplies) :

| Variable | Rôle |
|---|---|
| `SECRET_KEY` | Clé de chiffrement Django |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Base de données |
| `CORS_ALLOWED_ORIGINS` | Origines front autorisées |

> En `DEBUG=True`, les services externes (Flutterwave, Didit, Twilio) tournent avec des **placeholders** : pas besoin de vraies clés pour démarrer. Renseigne-les seulement pour tester ces intégrations.

Pour régénérer une `SECRET_KEY` :

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## 3. Démarrer les services

```bash
docker-compose up --build -d
```

Cela lance : **PostgreSQL, Redis, Django, Celery worker, Celery beat, pgAdmin, ngrok, backup**.

Vérifier l'état :

```bash
docker-compose ps
docker-compose logs -f web    # suivre le démarrage Django (Ctrl+C pour quitter)
```

Les migrations s'exécutent **automatiquement** au démarrage (`RUN_MIGRATIONS=True`).

---

## 4. Accès aux services

| Service | URL | Identifiants |
|---|---|---|
| API Django | http://localhost:8000 | — |
| Swagger (doc API) | http://localhost:8000/api/schema/swagger-ui/ | — |
| ReDoc | http://localhost:8000/api/schema/redoc/ | — |
| pgAdmin | http://localhost:5050 | `admin@alsaba.com` / `admin` |
| ngrok dashboard | http://localhost:4040 | — |

---

## 5. Créer un compte admin

```bash
docker-compose exec web python manage.py createsuperuser
```

Accès admin Django : http://localhost:8000/admin

---

## 6. Commandes utiles

```bash
# Arrêter les services (garde les données)
docker-compose down

# Arrêter ET supprimer les volumes (reset complet de la DB)
docker-compose down -v

# Redémarrer un service
docker-compose restart web

# Voir les logs d'un service
docker-compose logs -f celery_worker

# Ouvrir un shell dans le conteneur web
docker-compose exec web bash

# Lancer les migrations manuellement
docker-compose exec web python manage.py migrate
```

---

## 7. Activer les intégrations externes (optionnel)

Renseigne les valeurs dans `.env` puis `docker-compose up -d` pour appliquer :

- **Paiements** : `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_PUBLIC_KEY`, `FLUTTERWAVE_WEBHOOK_SECRET`, `FLUTTERWAVE_SANDBOX_CLIENT_ID/SECRET`
- **KYC** : `DIDIT_API_KEY`, `DIDIT_WEBHOOK_SECRET`
- **SMS** : `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- **Webhooks externes (ngrok)** : `NGROK_AUTH_TOKEN`
- **Monitoring** : `SENTRY_DSN`

---

## 8. Passage en production (`DEBUG=False`)

⚠️ En production, Django **refuse de démarrer** si l'un de ces éléments manque :

1. `ALLOWED_HOSTS` = vrai domaine (pas localhost)
2. `CORS_ALLOWED_ORIGINS` = origines réelles
3. `DIDIT_API_KEY` + `DIDIT_WEBHOOK_SECRET` (valeurs réelles)
4. Si `FLUTTERWAVE_ENVIRONMENT=production` : `FLUTTERWAVE_PRODUCTION_CLIENT_ID`, `..._CLIENT_SECRET`, `FLUTTERWAVE_PUBLIC_KEY`, `FLUTTERWAVE_WEBHOOK_SECRET`
5. Retirer le port `5432` exposé dans `docker-compose.yml`
6. Changer les identifiants pgAdmin par défaut

---

## 🛠 Dépannage

| Erreur | Cause | Solution |
|---|---|---|
| `required variable SECRET_KEY is missing` | `.env` absent ou vide | Vérifier que `.env` existe à la racine |
| `failed to connect to the docker API` | Docker Desktop éteint | Démarrer Docker Desktop |
| `open Dockerfile.backup: no such file` | Fichier manquant | Présent dans `docker/backup/Dockerfile.backup` |
| `NGROK_AUTH_TOKEN variable is not set` | Warning inoffensif | Ignorer, ou renseigner le token dans `.env` |
| Le service `web` redémarre en boucle | Migration ou DB pas prête | `docker-compose logs web` pour voir l'erreur |
