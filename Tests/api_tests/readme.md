# Tests API - ALSABA Backend

Ce dossier contient les tests pour l'API backend ALSABA.

## 📁 Structure

```
Tests/
├── api_tests/
│   ├── tests.http      # Tests REST Client (VS Code)
│   ├── test_flow.py    # Tests Python automatisés
│   └── readme.md       # Ce fichier
└── test_images/        # Images pour tests KYC
    ├── carte_identite_recto.jpg
    ├── carte_identite_verso.jpg
    ├── passport.jpg
    ├── permis_recto.jpg
    └── permis_verso.jpg
```

## 🧪 Tests REST Client (.http)

### Prérequis

1. **VS Code** avec l'extension [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.REST-Client)
2. **Serveur Django** en cours d'exécution sur `http://127.0.0.1:8000`

### Utilisation

1. Ouvrez `tests.http` dans VS Code
2. Cliquez sur "Send Request" au-dessus de chaque requête
3. Les variables sont automatiquement chaînées entre les requêtes

### Endpoints testés

| # | Endpoint | Méthode | Description |
|---|----------|---------|-------------|
| 1 | `/auth/phone/` | POST | Demande d'OTP |
| 2 | `/auth/verify/` | POST | Vérification OTP |
| 3 | `/auth/status/` | GET | Statut de session |
| 4 | `/auth/refresh/` | POST | Rafraîchir token JWT |
| 5 | `/profile/` | GET | Profil utilisateur |
| 6 | `/kyc/verify/` | POST | Vérification KYC |
| 7 | `/account/delete/` | POST | Demande suppression |
| 8 | `/account/delete/confirm/` | POST | Confirmer suppression |

### Flow de test complet

```
1. POST /auth/phone/           → Reçoit session_key
2. POST /auth/verify/          → Reçoit access_token + refresh_token
3. GET /profile/               → Vérifie le profil
4. POST /kyc/verify/           → Soumet documents KYC
5. GET /profile/               → Vérifie statut KYC
6. POST /account/delete/       → Demande suppression
7. POST /account/delete/confirm/ → Confirme suppression
```

## 🖼️ Images de test pour KYC

Pour tester les endpoints KYC, placez des images dans `Tests/test_images/` :

- `carte_identite_recto.jpg` - Recto carte d'identité
- `carte_identite_verso.jpg` - Verso carte d'identité
- `passport.jpg` - Page passeport
- `permis_recto.jpg` - Recto permis de conduire
- `permis_verso.jpg` - Verso permis de conduire

> ⚠️ **Note**: Utilisez des images de test, pas de vrais documents !

## 📋 Variables

Les variables sont définies en haut du fichier `tests.http` :

```http
@baseUrl = http://127.0.0.1:8000/api/accounts
@phoneNumber = 684499227
@countryCode = +212
@phoneNumberE164 = +212684499227
```

Modifiez ces valeurs selon vos besoins de test.

## 🔐 Authentification

Après la vérification OTP réussie, le token est automatiquement stocké :

```http
@authToken = {{verifyOtp.response.body.auth.access_token}}
```

Ce token est utilisé dans toutes les requêtes authentifiées via :

```http
Authorization: Bearer {{authToken}}
```

## ✅ Tests inclus

### Tests fonctionnels
- ✅ Inscription nouveau utilisateur
- ✅ Connexion utilisateur existant
- ✅ Vérification OTP valide/invalide
- ✅ Gestion des sessions
- ✅ Rafraîchissement de token
- ✅ Récupération profil
- ✅ Vérification KYC (carte, passeport, permis)
- ✅ Suppression de compte

### Tests d'erreur
- ✅ Numéro de téléphone invalide
- ✅ Code OTP incorrect
- ✅ Session expirée
- ✅ Token invalide/expiré
- ✅ Champs manquants
- ✅ Types de document invalides

### Tests de sécurité
- ✅ Injection SQL
- ✅ XSS
- ✅ Overflow (données trop longues)
- ✅ Headers malveillants

## 🚀 Lancer le serveur

```bash
cd /home/salim/Projets/ALSABA/alsabaBackend
source venv/bin/activate
cd Project
python manage.py runserver
```

## 📝 Notes

- Les OTP sont envoyés via Didit en production
- En développement, vérifiez les logs pour voir les codes
- Le rate limiting est désactivé par défaut (commenté)