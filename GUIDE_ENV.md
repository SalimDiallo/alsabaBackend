# 📋 Guide des Variables d'Environnement Docker

## 🚀 Configuration rapide

### 1. Créer le fichier .env

```bash
# Copier le fichier exemple
cp env.example .env

# Éditer le fichier .env avec vos valeurs
nano .env
# ou
vim .env
```

### 2. Remplir les variables importantes

Ouvrez `.env` et remplacez les valeurs par défaut :

#### Variables obligatoires (minimum pour démarrer) :

```env
# Django
SECRET_KEY=votre-clé-secrète-très-longue-et-aléatoire
DEBUG=True

# Base de données (déjà configurées par défaut)
POSTGRES_DB=alsaba_db
POSTGRES_USER=alsaba_user
POSTGRES_PASSWORD=alsaba_password
```

#### Variables optionnelles (pour fonctionnalités avancées) :

```env
# Flutterwave (pour les paiements)
FLUTTERWAVE_ENVIRONMENT=sandbox
FLUTTERWAVE_SANDBOX_CLIENT_ID=votre_client_id
FLUTTERWAVE_SANDBOX_CLIENT_SECRET=votre_client_secret
FLUTTERWAVE_SANDBOX_ENCRYPTION_KEY=votre_encryption_key

# Didit (pour KYC)
DIDIT_API_KEY=votre_didit_api_key
DIDIT_WEBHOOK_SECRET=votre_webhook_secret
```

### 3. Utiliser avec Docker Compose

Docker Compose lit automatiquement le fichier `.env` à la racine du projet.

```bash
# Démarrer les services (utilise automatiquement .env)
sudo docker-compose up -d

# Vérifier que les variables sont chargées
sudo docker-compose config
```

## 📝 Comment ça fonctionne

### Dans docker-compose.yml

Les variables sont référencées avec `${VARIABLE_NAME:-default_value}` :

```yaml
environment:
  - DEBUG=${DEBUG:-True}  # Utilise DEBUG du .env, sinon True
  - SECRET_KEY=${SECRET_KEY:-default-key}
```

### Dans Django (settings.py)

Django charge automatiquement le fichier `.env` grâce à `python-dotenv` :

```python
from dotenv import load_dotenv
load_dotenv()  # Charge .env

# Utilisation
FLUTTERWAVE_SANDBOX_CLIENT_ID = os.getenv('FLUTTERWAVE_SANDBOX_CLIENT_ID', '')
```

## 🔒 Sécurité

### ⚠️ IMPORTANT : Ne jamais commiter le fichier .env

Le fichier `.env` contient des secrets et doit être dans `.gitignore` :

```bash
# Vérifier que .env est dans .gitignore
echo ".env" >> .gitignore
```

### ✅ Utiliser env.example pour le partage

Le fichier `env.example` peut être commité (sans valeurs sensibles) pour servir de modèle.

## 🧪 Tester les variables

### Vérifier dans un conteneur

```bash
# Entrer dans le conteneur Django
sudo docker-compose exec web bash

# Voir les variables d'environnement
env | grep FLUTTERWAVE
env | grep DATABASE
```

### Vérifier depuis l'extérieur

```bash
# Voir la configuration complète
sudo docker-compose config

# Voir les variables d'un service spécifique
sudo docker-compose exec web env
```

## 🔄 Recharger les variables

Après modification du fichier `.env` :

```bash
# Redémarrer les services pour charger les nouvelles variables
sudo docker-compose down
sudo docker-compose up -d
```

## 📚 Variables disponibles

### Django
- `DEBUG` : Mode debug (True/False)
- `SECRET_KEY` : Clé secrète Django (générer avec `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- `ALLOWED_HOSTS` : Hôtes autorisés (séparés par des virgules)

### Base de données
- `POSTGRES_DB` : Nom de la base de données
- `POSTGRES_USER` : Utilisateur PostgreSQL
- `POSTGRES_PASSWORD` : Mot de passe PostgreSQL
- `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` : Variables pour Django

### Redis/Celery
- `CELERY_BROKER_URL` : URL du broker Redis
- `CELERY_RESULT_BACKEND` : Backend de résultats Redis

### Flutterwave
- `FLUTTERWAVE_ENVIRONMENT` : sandbox ou production
- `FLUTTERWAVE_SANDBOX_*` : Configuration sandbox
- `FLUTTERWAVE_PRODUCTION_*` : Configuration production

### Didit
- `DIDIT_API_KEY` : Clé API Didit
- `DIDIT_WEBHOOK_SECRET` : Secret pour valider les webhooks

## 🆘 Dépannage

### Les variables ne sont pas chargées

1. Vérifier que le fichier `.env` existe à la racine du projet
2. Vérifier la syntaxe (pas d'espaces autour du `=`)
3. Redémarrer les conteneurs : `sudo docker-compose restart`

### Erreur "Variable d'environnement manquante"

Vérifier que toutes les variables requises sont dans `.env` ou ont des valeurs par défaut dans `docker-compose.yml`.




