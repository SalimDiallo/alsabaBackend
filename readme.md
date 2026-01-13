# ALSABA Backend

Backend Django pour le projet ALSABA avec authentification JWT.

## 🚀 Démarrage rapide (Développement local avec SQLite)

```bash
# 1. Créer un environnement virtuel
python3 -m venv venv
source venv/bin/activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Copier le fichier de configuration
cp .env.example .env

# 4. Appliquer les migrations
cd Project
python manage.py migrate

# 5. Créer un superutilisateur (optionnel)
python manage.py createsuperuser

# 6. Lancer le serveur
python manage.py runserver
```

📌 **URL disponible**: http://localhost:8000

---

## 🐳 Démarrage avec Docker (PostgreSQL)

> ⚠️ Pour utiliser Docker avec PostgreSQL, décommentez les variables `DATABASE_*` dans `.env`

```bash
# Construire et démarrer les conteneurs
docker-compose up --build

# Démarrer en arrière-plan
docker-compose up -d --build

# Voir les logs
docker-compose logs -f

# Arrêter les conteneurs
docker-compose down

# Arrêter et supprimer les volumes (reset BDD)
docker-compose down -v
```

### 📌 URLs disponibles (Docker)

| Service  | URL                    | Identifiants            |
|----------|------------------------|-------------------------|
| Django   | http://localhost:8000  | -                       |
| pgAdmin  | http://localhost:5050  | admin@alsaba.com / admin |

### 🔧 Connexion pgAdmin à PostgreSQL

Dans pgAdmin, créez une nouvelle connexion avec :

- **Host**: db
- **Port**: 5432
- **Database**: alsaba_db
- **Username**: alsaba_user
- **Password**: alsaba_password

---

## 📁 Structure du projet

```
alsabaBackend/
├── Project/               # Code Django principal
│   ├── Accounts/          # Application Authentification
│   ├── Project/           # Configuration Django
│   └── manage.py
├── Tests/                 # Tests API
├── docker-compose.yml     # Configuration Docker
├── requirements.txt       # Dépendances Python
└── .env.example           # Variables d'environnement exemple
```

---

## 🔐 API Endpoints

Testez les endpoints avec le fichier `Tests/api_tests/tests.http`

### Authentification
- `POST /api/accounts/request-otp/` - Demande d'OTP
- `POST /api/accounts/verify-otp/` - Vérification OTP
- `POST /api/accounts/login/` - Connexion

---

## 📚 Documentation

- [Didit API Authentication](https://docs.didit.me/reference/api-authentication)