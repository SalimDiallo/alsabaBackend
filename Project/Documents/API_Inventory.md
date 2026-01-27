# Documentation Technique Ultime - API Alsaba Backend

Ce document est le référentiel complet de l'infrastructure logicielle Alsaba. Il détaille chaque point de terminaison, les flux de données, les protocoles de sécurité et les intégrations tierces (Didit & Flutterwave).

---

## 🏛️ Architecture & Standards de Données

### 1. Précision Numérique (Mode "Cents")
Le backend ne manipule JAMAIS de types `float` pour les calculs financiers afin d'éviter les erreurs d'arrondi (`0.1 + 0.2 != 0.3`).
- **Modèle de Données** : Les soldes et montants sont stockés en `BigInteger` nommé `*_cents`.
- **Propriété Python** : Utilisation de `Decimal` (librairie standard) pour les calculs de commissions.
- **Réponse API** : Les montants sont sérialisés en `float` pour la compatibilité frontend, mais le calcul source reste en `Decimal` de bout en bout.

### 2. Sécurité & Permissions
- **IsAuthenticated** : Requis pour la majorité des endpoints. Identifie l'utilisateur via le header `Authorization: Bearer <token>`.
- **IsAdminUser** : Requis pour les actions critiques (confirmations manuelles, statistiques globales, forçage de statut).
- **Rate Limiting** : Appliqué sur l'authentification pour prévenir le brute-force.

---

## 🔐 Application : Accounts (Gestion de l'Identité)

### Flux d'Authentification OTP (Didit)

#### [POST] `/api/accounts/auth/phone/`
- **Rôle** : Demande d'un code de vérification.
- **Payload** :
  ```json
  { "phone_number": "0612345678", "country_code": "+33" }
  ```
- **Logique Métier** :
  1. Standardisation du numéro au format **E.164** via `phonenumbers`.
  2. Vérification des limites (Max 3 SMS par 5 min par IP/Numéro).
  3. Appel API `Didit` pour l'envoi du code.
  4. Création d'une session en cache (Redis/Local) avec un TTL de 15 minutes.
- **Réponse** : `session_key` (UUID) et `user_exists` (bool).

#### [POST] `/api/accounts/auth/verify/`
- **Rôle** : Validation du code et connexion.
- **Payload** :
  ```json
  { "phone_number": "+33612345678", "code": "123456", "session_key": "uuid-..." }
  ```
- **Logique Métier** :
  1. Validation du code auprès de `Didit`.
  2. Si valide : Analyse des métadonnées (Détection VOIP/Discardable).
  3. **Auto-Inscription** : Si l'utilisateur n'existe pas, création du profil et d'un wallet vide.
  4. Mise à jour de `last_login` et génération des tokens JWT.
- **Réponse** : `access`, `refresh` et `user` (objet complet).

#### [POST] `/api/accounts/resend/`
- **Logic** : Utilise la `session_key` pour renvoyer un code sans redemander le numéro.

---

## 💰 Application : Wallet (Mouvements de Fonds)

### 1. Dépôts (Cash-In)

#### [POST] `/api/wallet/deposit/`
- **Logic** : Initiation d'un paiement via Flutterwave.
- **Payload** :
  ```json
  { "amount": 100.50, "payment_method": "card", "save_payment_method": true }
  ```
- **Logique Interne** :
  1. **Audit KYC** : Rejet si `kyc_status != 'verified'`.
  2. **Fee calculation** : Applique `WalletService._calculate_deposit_fee` (Decimal).
  3. **Flutterwave Redirect** : Génère un lien de paiement dynamique.
  4. **Persistance** : Crée une `Transaction` au statut `pending`.

#### [POST] `/api/wallet/webhook/` (Entrée Système)
- **Logic** : Automate asynchrone pour Flutterwave.
- **Sécurité** : Vérification du header `X-Flutterwave-Signature` (HMAC SHA256).
- **Logique de Crédit** : 
  - Si `event == "charge.completed"`, le système cherche la transaction via `tx_ref`.
  - Effectue un `transaction.mark_completed()` qui incrémente atomiquement `wallet.balance_cents`.
  - Marque `balance_adjusted = True`.

---

### 2. Retraits (Cash-Out)

#### [POST] `/api/wallet/withdraw/`
- **Rôle** : Sortie de fonds vers Banque ou Orange Money.
- **Protocole de Sécurité (Pessimistic Locking)** :
  1. `wallet = Wallet.objects.select_for_update().get(...)` : Verrouille la ligne en base de données.
  2. Vérification du solde suffisant (`amount + fees`).
  3. **Débit immédiat** du solde pour éviter qu'un utilisateur lance 10 retraits en parallèle.
  4. Appel API Flutterwave Transfer.
  5. En cas d'erreur API immédiate, le solde est **restauré**. Sinon, on attend le Webhook.

---

### 3. Endpoints d'Administration (Staff Only)

#### [POST] `/api/wallet/deposit/<id>/confirm/`
- **Rôle** : Validation manuelle "Force Credit".
- **Usage** : Si un utilisateur a payé mais que le webhook ne nous est jamais parvenu.
- **Permission** : **IsAdminUser**.

#### [PATCH] `/api/wallet/transactions/<id>/update-status/`
- **Rôle** : Correction de statut par un agent.
- **Logique** : Permet de rectifier une erreur humaine ou technique. Si le statut passe de `failed` à `completed`, le système crédite automatiquement le wallet.

---

## 🛠️ Outils & Services Utilitaires

#### [GET] `/api/wallet/fees/estimate/`
- **Logic** : Permet au Frontend d'afficher les frais en temps réel avant validation.
- **Fonctionnement** : Appelle les méthodes statiques du `WalletService` sans modifier la base de données.

#### [GET] `/api/wallet/transactions/`
- **Filtres supportés** : `transaction_type`, `status`, `payment_method`, `date_from`, `date_to`.
- **Pagination** : Supporte `limit` et `offset`.

#### [POST] `/api/wallet/transactions/<id>/retry/`
- **Logic** : (En cours) Permet de relancer une transaction échouée en ré-interrogeant Flutterwave ou en créant un nouveau lien.
