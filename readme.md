# 🌍 ALSABA - Plateforme de Trading P2P

Alsaba est une plateforme d'échange de devises de pair-à-pair sécurisée, conçue pour faciliter le transfert de valeur entre zones monétaires (Ex: EUR <-> XOF).

## 🚀 Démarrage Rapide (Docker)

```bash
# Construire et démarrer les conteneurs
docker-compose up --build -d

# Voir les logs
docker-compose logs -f

# Arrêter les conteneurs
docker-compose down
```

## 📌 URLs et Documentation
- **API Base** : `http://localhost:8000/api/`
- **Swagger UI** : `http://localhost:8000/api/schema/swagger-ui/`
- **Redoc** : `http://localhost:8000/api/schema/redoc/`
- **pgAdmin** : `http://localhost:5050` (admin@alsaba.com / admin)

## 🛠 Nouveautés et Mises à Jour

### 🆔 KYC Didit v3 & Face Match
Le système utilise désormais l'**API Didit v3** pour une vérification d'identité conforme :
- Support flexible des passeports (recto/verso).
- **Face Match** : Comparaison biométrique entre le selfie de l'utilisateur et son document ID.
- Sécurité renforcée des webhooks via signature HMAC et timestamping.

### 🔄 Échanges P2P & Offres Étrangères
Le moteur d'échange (`Offer app`) a été enrichi :
- **Endpoint `/api/offers/foreign/`** : Affiche uniquement les offres provenant d'autres pays.
- **Filtrage Avancé** : Recherche par devises (`currency_sell`, `currency_buy`) et montants.
- **Système de Suggestions** : Moteur hybride (Règles + ML) pour recommander des offres pertinentes.

---
*Note : Pour les développeurs, une collection Insomnia est disponible dans le dossier `insomnia/`.*