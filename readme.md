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


📌 URLs disponibles
Service	URL	Identifiants
Django	http://localhost:8000	-
pgAdmin	http://localhost:5050	admin@alsaba.com / admin
🔧 Connexion pgAdmin à PostgreSQL
Dans pgAdmin, créez une nouvelle connexion avec :

Host: db
Port: 5432
Database: alsaba_db
Username: alsaba_user
Password: alsaba_password
