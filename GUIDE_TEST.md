# 🧪 Guide de Test - API ALSABA

## 1. Vérifier que les services sont démarrés

```bash
# Voir tous les conteneurs
sudo docker-compose ps

# Voir les logs
sudo docker-compose logs -f web

# Vérifier que le serveur répond
curl http://127.0.0.1:8000/api/accounts/auth/phone/
```

## 2. Méthodes de test

### A. Script de test automatique

```bash
./test_api.sh
```

### B. Tests avec curl (ligne de commande)

#### 1. Demander un OTP
```bash
curl -X POST http://127.0.0.1:8000/api/accounts/auth/phone/ \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "684499227",
    "country_code": "+212"
  }'
```

#### 2. Vérifier l'OTP (remplacer CODE_RECU et SESSION_KEY)
```bash
curl -X POST http://127.0.0.1:8000/api/accounts/auth/verify/ \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+212684499227",
    "code": "CODE_RECU",
    "session_key": "SESSION_KEY"
  }'
```

#### 3. Obtenir le profil (remplacer TOKEN)
```bash
curl -X GET http://127.0.0.1:8000/api/accounts/profile/ \
  -H "Authorization: Bearer TOKEN"
```

### C. Tests avec le fichier HTTP (VS Code)

1. Installez l'extension **REST Client** dans VS Code
2. Ouvrez le fichier `Tests/api_tests/tests.http`
3. Cliquez sur "Send Request" au-dessus de chaque requête

### D. Tests avec Insomnia/Postman

Importez le fichier `insomnia/alsaba.yaml` dans Insomnia ou créez manuellement les requêtes.

## 3. Endpoints à tester

### Authentification
- ✅ `POST /api/accounts/auth/phone/` - Demander OTP
- ✅ `POST /api/accounts/auth/verify/` - Vérifier OTP
- ✅ `POST /api/accounts/auth/resend/` - Renvoyer OTP
- ✅ `GET /api/accounts/auth/status/` - Statut d'authentification

### Profil
- ✅ `GET /api/accounts/profile/` - Obtenir le profil (auth requise)
- ✅ `PATCH /api/accounts/profile/` - Mettre à jour le profil (auth requise)

### KYC
- ✅ `POST /api/accounts/kyc/verify/` - Vérification KYC (auth requise)

### Suppression de compte
- ✅ `POST /api/accounts/delete/` - Demander suppression (auth requise)
- ✅ `POST /api/accounts/delete/confirm/` - Confirmer suppression (auth requise)

## 4. Vérification des services Docker

```bash
# Voir l'état des services
sudo docker-compose ps

# Voir les logs en temps réel
sudo docker-compose logs -f

# Voir les logs d'un service spécifique
sudo docker-compose logs -f web
sudo docker-compose logs -f celery_worker
sudo docker-compose logs -f celery_beat

# Vérifier la base de données
sudo docker-compose exec db psql -U alsaba_user -d alsaba_db -c "\dt"
```

## 5. Tests de santé (Health Checks)

```bash
# Vérifier que Django répond
curl http://127.0.0.1:8000/

# Vérifier Redis
sudo docker-compose exec redis redis-cli ping

# Vérifier PostgreSQL
sudo docker-compose exec db pg_isready -U alsaba_user
```

## 6. Dépannage

### Le serveur ne répond pas
```bash
# Vérifier les logs
sudo docker-compose logs web

# Redémarrer le service
sudo docker-compose restart web
```

### Erreur de connexion à la base de données
```bash
# Vérifier que PostgreSQL est démarré
sudo docker-compose ps db

# Vérifier les migrations
sudo docker-compose exec web python manage.py showmigrations
```

### Erreur Redis/Celery
```bash
# Vérifier Redis
sudo docker-compose logs redis

# Vérifier Celery Worker
sudo docker-compose logs celery_worker
```

## 7. Tests avancés

### Tester avec plusieurs utilisateurs
```bash
# Utilisateur 1
curl -X POST http://127.0.0.1:8000/api/accounts/auth/phone/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "684499227", "country_code": "+212"}'

# Utilisateur 2
curl -X POST http://127.0.0.1:8000/api/accounts/auth/phone/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "660620565", "country_code": "+212"}'
```

### Tester les erreurs
```bash
# Numéro invalide
curl -X POST http://127.0.0.1:8000/api/accounts/auth/phone/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "123", "country_code": "+212"}'

# Code OTP invalide
curl -X POST http://127.0.0.1:8000/api/accounts/auth/verify/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+212684499227", "code": "000000", "session_key": "invalid"}'
```

