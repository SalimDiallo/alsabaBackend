# Master API Documentation - Alsaba Backend (100% Exhaustif)

Ce document est la référence absolue du backend Alsaba. Il recense les **27 points d'entrée** des applications `Accounts` et `Wallet`, détaillant leur fonctionnement interne, leurs paramètres et leur logique de sécurité.

---

## 🏗️ Standards du Système

### 1. Précision Monétaire (Architecture "Cents")
- **Base 100** : Tous les montants en base de données sont des entiers (`100` = 1.00 unité).
- **Calculs** : Utilisation exclusive du type `Decimal` pour les commissions afin d'éviter les erreurs d'arrondi des `float`.
- **Atomicité** : Utilisation de `F()` expressions et `select_for_update()` pour garantir l'intégrité des soldes lors de transactions concurrentes.

### 2. Sécurité & Permissions
- **JWT** : Authentification par jeton (`Authorization: Bearer <token>`).
- **IsAdminUser** : Restriction stricte des endpoints de forçage et de statistiques.
- **Webhook Check** : Vérification de signature HMAC SHA256 pour les entrées Flutterwave.

---

## 🔐 Application : Accounts (9 Endpoints)

### A. Authentification OTP (Didit)

#### 1. [POST] `/api/accounts/auth/phone/` (`PhoneAuthView`)
- **Logique** : Initie le flux. Standardise le numéro au format E.164. Vérifie le rate limit (3/5min). Appelle Didit API pour l'envoi SMS. Stocke la session en cache.
- **Payload** : `{ "phone_number": "str", "country_code": "+33" }`

#### 2. [POST] `/api/accounts/auth/verify/` (`VerifyOTPView`)
- **Logique** : Valide le code. Si valide, vérifie si le numéro est "Fraudulent" (VOIP). Crée l'utilisateur et le Wallet si nécessaire. Retourne les tokens JWT.
- **Payload** : `{ "phone_number": "E164", "code": "6 chars", "session_key": "uuid" }`

#### 3. [POST] `/api/accounts/resend/` (`ResendOTPView`)
- **Logique** : Relance un envoi Didit pour une session active sans redemander le numéro.
- **Payload** : `{ "session_key": "uuid" }`

#### 4. [GET] `/api/accounts/auth/status/` (`AuthStatusView`)
- **Logique** : Retourne le temps restant avant expiration de la session OTP.

#### 5. [POST] `/api/accounts/auth/refresh/` (`TokenRefreshView`)
- **Logique** : Standard SimpleJWT. Échange un `refresh` token contre un nouveau `access` token.
- **Payload** : `{ "refresh": "token" }`

### B. Gestion du Profil & KYC

#### 6. [GET/PATCH] `/api/accounts/profile/` (`ProfileView`)
- **Logique** : **GET** retourne le profil détaillé (completion %, next steps). **PATCH** permet de mettre à jour le nom, l'email, la ville, etc.

#### 7. [POST] `/api/accounts/kyc/verify/` (`KYCVerifyView`)
- **Logique** : Envoie les images d'identité (recto/verso) à Didit. Met à jour le statut `kyc_status` (pending -> verified/rejected). Enrichit automatiquement le profil avec les données extraites (nom, date de naissance).
- **Payload** : `{ "document_type": "id_card|passport", "front_image": "file", "back_image": "file" }`

### C. Suppression (Soft Delete)

#### 8. [POST] `/api/accounts/delete/` (`AccountDeleteRequestView`)
- **Logique** : Initie la suppression via un flux OTP similaire à la connexion.

#### 9. [POST] `/api/accounts/delete/confirm/` (`AccountDeleteConfirmView`)
- **Logique** : Valide l'OTP. Désactive l'utilisateur, anonymise le numéro (préfixe `deleted_timestamp_`) et réinitialise les infos sensibles.

---

## 💰 Application : Wallet (18 Endpoints)

### A. Portefeuille & Dépôts

#### 10. [GET] `/api/wallet/` (`WalletView`)
- **Logique** : Solde actuel (converti en unité via balance_cents) + 5 dernières transactions.

#### 11. [POST] `/api/wallet/deposit/` (`DepositView`)
- **Logique** : Calcule les frais. Crée la transaction `pending`. Génère le lien Flutterwave.
- **Payload** : `{ "amount": 10.0, "payment_method": "card|orange_money" }`

#### 12. [POST] `/api/wallet/deposit/<id>/confirm/` (`ConfirmDepositView`)
- **Permission** : **ADMIN SEULEMENT**.
- **Logique** : Force le crédit du compte. À utiliser si un paiement est confirmé chez Flutterwave mais que le webhook a échoué.

#### 13. [POST] `/api/wallet/deposit/<id>/cancel/` (`CancelDepositView`)
- **Logique** : Passe une transaction `pending` en `cancelled`.

### B. Retraits (Cash-Out)

#### 14. [POST] `/api/wallet/withdraw/` (`WithdrawalView`)
- **Logique** : **Verrouille le solde**. Débite immédiatement (montant + frais). Appelle Flutterwave Transfer. Si erreur immédiate, rembourse le solde.

#### 15. [POST] `/api/wallet/withdraw/<id>/confirm/` (`ConfirmWithdrawalView`)
- **Permission** : **ADMIN SEULEMENT**.
- **Logique** : Marque le retrait comme réussi si le statut était resté bloqué en `processing`.

#### 16. [POST] `/api/wallet/withdraw/<id>/cancel/` (`CancelWithdrawalView`)
- **Logique** : Annule le retrait et **rembourse** l'utilisateur si la transaction n'est pas encore finalisée.

### C. Transactions & Historique

#### 17. [GET] `/api/wallet/transactions/` (`TransactionListView`)
- **Logique** : Historique complet avec filtres (`status`, `transaction_type`, `date_from`).

#### 18. [GET] `/api/wallet/transactions/<id>/` (`TransactionDetailView`)
- **Logique** : Vue complète d'un seul mouvement.

#### 19. [GET] `/api/wallet/transactions/<id>/status/` (`TransactionStatusView`)
- **Logique** : Force un appel API à Flutterwave pour synchroniser le statut local avec le statut réel du prestataire.

#### 20. [POST] `/api/wallet/transactions/<id>/retry/` (`RetryTransactionView`)
- **Logique** : Tente de relancer une transaction échouée (si applicable).

### D. Méthodes de Paiement (Saved Cards/Accounts)

#### 21. [POST] `/api/wallet/fees/estimate/` (`EstimateFeesView`)
- **Logique** : Calculateur de frais en temps réel. Ne modifie pas la base de données.

#### 22. [GET/POST] `/api/wallet/payment-methods/` (`PaymentMethodListView`)
- **Logique** : **GET** liste les cartes/comptes sauvegardés. **POST** permet d'en ajouter un nouveau manuellement.

#### 23. [GET/PATCH/DELETE] `/api/wallet/payment-methods/<id>/` (`PaymentMethodDetailView`)
- **Logique** : Gère une méthode spécifique (Détail, renommage, ou suppression logique).

#### 24. [POST] `/api/wallet/payment-methods/<id>/set-default/` (`PaymentMethodSetDefaultView`)
- **Logique** : Définit la méthode comme celle à utiliser par défaut pour les futurs flux.

### E. Système & Admin

#### 25. [POST] `/api/wallet/webhook/` (`FlutterwaveWebhookView`)
- **Logique** : Traite les signaux asynchrones. Vérifie la signature. Crédite les dépôts. Confirme les retraits. **C'est le coeur automatisé du système.**

#### 26. [PATCH] `/api/wallet/transactions/<id>/update-status/` (`UpdateTransactionStatusView`)
- **Permission** : **ADMIN SEULEMENT**.
- **Logique** : Permet de modifier manuellement le statut d'une transaction et gère automatiquement l'ajustement du solde du wallet associé.

#### 27. [GET] `/api/wallet/stats/` (`WalletStatsView`)
- **Permission** : **ADMIN SEULEMENT**.
- **Logique** : Dashboard global : Volume total, commissions cumulées, santé du système.
