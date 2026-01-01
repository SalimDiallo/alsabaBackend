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
Name: Alsba

Master password for pgAdmin
Maintenance database = postgres
alsaba_master_password


==============================
POUR TOI BOSS
==============================


Test des endpoints d'authentification
**Prioritaires
Test 1.1 → Vérifie que l'envoi fonctionne
Test 2.1 → Vérifie la création de compte
Test 1.2 → Vérifie le login
Test 2.5 → Vérifie la connexion
Les trois endpoint que nous testons sont les trois dernier dans Accounts/urls.py
Tu dois me fournir la clé API qui commence par dp_test ou dp_live pour que je puisse performer les test de mon coté aussi
Le nettoyqge dutravail avec twilio je le ferai après je l'ai gardé pour quetion de logique metier
ils ont indiqué comment l'avoir dans la doc Ge started Athentication
Tu pourras tester les nendpoint toi meme aussi avec Tests/testEndpoints.http

https://docs.didit.me/reference/api-authentication