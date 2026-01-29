# Documentation Exhaustive de l'API Alsaba

Cette documentation détaille l'intégralité des points d'entrée (endpoints) de l'API Alsaba.

---

## 🔑 Authentification & Sécurité

L'authentification repose sur des tokens **JWT**.
- **Header requis** : `Authorization: Bearer <votre_access_token>`
- **Format des erreurs** : `{ "success": false, "error": "Message", "code": "error_code" }`

---

## 📱 Module Accounts (Utilisateurs & Profil)

### 1. Authentification Téléphonique (Phase 1)
`POST /api/accounts/auth/phone/`
- **Action** : Envoie un code OTP par SMS via Didit.
- **Payload** : `{ "phone_number": "+22177XXXXXXX", "country_code": "+221" }`
- **Réponse** : `{ "session_key": "auth_xxx", "expires_in": 300, ... }`

### 2. Vérification OTP (Phase 2)
`POST /api/accounts/auth/verify/`
- **Action** : Vérifie le code et connecte l'utilisateur.
- **Payload** : `{ "phone_number": "+221...", "code": "123456", "session_key": "..." }`
- **Réponse** : Retourne les tokens `access` et `refresh`.

### 3. Renvoyer le Code OTP
`POST /api/accounts/resend/`
- **Payload** : `{ "session_key": "auth_xxx" }`

### 4. Statut de la Session Auth
`GET /api/accounts/auth/status/`
- **Query Params** : `?session_key=auth_xxx`
- **Usage** : Vérifier si une session OTP est encore valide côté frontend.

### 5. Rafraîchir le Token
`POST /api/accounts/auth/refresh/`
- **Payload** : `{ "refresh": "<votre_refresh_token>" }`

### 6. Profil Utilisateur
`GET /api/accounts/profile/` : Récupère le profil complet + score de complétion.
`PATCH /api/accounts/profile/` : Mise à jour partielle.
- **Champs acceptés** : `first_name`, `last_name`, `email`, `city`, `postal_code`, `state`.

### 7. Vérification d'Identité (KYC)
`POST /api/accounts/kyc/verify/`
- **Payload (Multipart/form-data)** :
    - `document_type`: (PASSPORT, ID_CARD, DRIVERS_LICENSE)
    - `front_image`: Fichier image
    - `back_image`: Fichier image (si requis)

### 8. Suppression de Compte
`POST /api/accounts/delete/` : Demande de suppression. Envoie un OTP de confirmation.
`POST /api/accounts/delete/confirm/` : Valide l'OTP et effectue le "Soft Delete".
- **Payload Confirm** : `{ "code": "123456", "session_key": "delete_xxx" }`

---

## 💰 Module Wallet (Portefeuille & Finance)

### 1. Vue du Portefeuille
`GET /api/wallet/`
- **Contenu** : Solde, devise, 5 dernières transactions.

### 2. Statistiques Admin
`GET /api/wallet/stats/` (Staff uniquement)
- **Contenu** : Volume total des dépôts/retraits, nombre de transactions.

### 3. Estimation des Frais
`POST /api/wallet/fees/estimate/`
- **Payload** : `{ "transaction_type": "deposit", "amount": 1000, "payment_method": "card" }`

---

## 💸 Flux des Transactions

### Dépôts (Cash-in)
1. `POST /api/wallet/deposit/` : Initie le dépôt. Retourne un `payment_link` (Flutterwave) et un `transaction_id`.
2. `POST /api/wallet/deposit/<uuid>/confirm/` : Confirmation forcée (Admin/Système).
3. `POST /api/wallet/deposit/<uuid>/cancel/` : Annulation explicite.

### Retraits (Cash-out)
1. `POST /api/wallet/withdraw/` : Initie le retrait (débite le solde immédiatement).
2. `POST /api/wallet/withdraw/<uuid>/confirm/` : Confirmation de réception des fonds par l'utilisateur.
3. `POST /api/wallet/withdraw/<uuid>/cancel/` : Annulation du retrait et **remboursement automatique** du solde.

### Gestion des Transactions
- `GET /api/wallet/transactions/` : Liste paginée des transactions.
    - Filtres : `transaction_type`, `status`, `date_from`, `date_to`.
- `GET /api/wallet/transactions/<uuid>/` : Détails d'une opération.
- `GET /api/wallet/transactions/<uuid>/status/` : Vérifie le statut en temps réel (inclut le statut Flutterwave).
- `POST /api/wallet/transactions/<uuid>/retry/` : Relance une transaction échouée (si applicable).
- `PATCH /api/wallet/transactions/<uuid>/update-status/` : Mise à jour manuelle du statut (Admin).

---

## 💳 Méthodes de Paiement (Saved Methods)

- `GET /api/wallet/payment-methods/` : Liste vos méthodes enregistrées (Cartes, Orange Money, Comptes Bancaires).
- `POST /api/wallet/payment-methods/` : Enregistre une nouvelle méthode.
    - Payload requis dépend du `method_type` (card, bank_account, orange_money).
- `GET | PATCH | DELETE /api/wallet/payment-methods/<uuid>/` : Gérer une méthode spécifique.
- `POST /api/wallet/payment-methods/<uuid>/set-default/` : Définit la méthode par défaut.

---

## 🏗️ Webhooks & Intégrations

### Flutterwave Webhook
`POST /api/wallet/webhook/`
- **Usage** : Traitement automatique des résultats de paiement et de transfert.
- **Sécurité** : Supporte la vérification via `Secret Hash` (Header `verif-hash`) ou HMAC.
