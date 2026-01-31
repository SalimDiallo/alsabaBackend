# 🧪 Guide de Test Alsaba API (Insomnia v2.0)

Ce dossier contient la collection Insomnia mise à jour pour tester l'intégralité des **endpoints** de l'API Alsaba, incluant les nouvelles fonctionnalités (Disputes, Notifications, Sécurité).

## 🚀 Installation
1.  Ouvrez **Insomnia**.
2.  Cliquez sur **Create** > **Import**.
3.  Sélectionnez le fichier `alsaba.yaml` présent dans ce dossier.
4.  Une fois importé, configurez votre `access_token` dans l'environnement (Ctrl+E).

---

## 🔐 Phase 1 : Authentification
*Indispensable pour toutes les autres requêtes.*
1.  **Auth: 1. Phone Auth** : Envoie un OTP.
2.  **Auth: 2. Verify OTP** : Récupère les tokens JWT (`access`). Mettez ce token dans l'environnement Insomnia.

---

## 👤 Phase 2 : Profil & KYC
1.  **Profile: View/Update** : Voir et modifier vos informations.
2.  **KYC: Submit Verification** : Uploader ID et Selfie.
3.  **Webhook: Didit KYC** : Simuler la validation par Didit.

---

## 💰 Phase 3 : Wallet (Portefeuille)
1.  **Wallet: Deposit** : Initier un dépôt (Carte/Orange Money).
2.  **Wallet: Withdraw** : Simuler un retrait.
3.  **Wallet: PM** : Gérer les méthodes de paiement sauvegardées.
4.  **Admin: Update Status** : (Admin) Forcer le statut d'une transaction bloquée.

---

## 🤝 Phase 4 : Offres P2P & Escrow
1.  **Offer: Create** : Vendeur (A1) crée une annonce.
2.  **Offer: Accept** : Acheteur (A2) accepte.
3.  **Offer: Validate** : Vendeur (A1) valide le match.
4.  **Offer: Confirm** : Finalisation automatique (fonds libérés).

---

## ⚖️ Phase 5 : Gestion des Litiges (Disputes) - **NOUVEAU**
*En cas de problème entre vendeur et acheteur.*
1.  **Dispute: Initiate** : Signaler un problème ("Je n'ai pas reçu l'argent").
2.  **Dispute: List/Detail** : Voir l'état du litige.
3.  **Dispute: Resolve** : (Admin) Trancher en faveur du vendeur ou de l'acheteur.

---

## 🔔 Phase 6 : Notifications
1.  **Notifications: Register Device** : Enregistrer un téléphone (FCM Token).
2.  **Notifications: List** : Voir l'historique des notifs in-app.

---

## 💡 Notes Importantes
*   **Environnement** : La collection utilise une variable `{{ base_url }}` (défaut: `http://127.0.0.1:8000`).
*   **Tokens** : La plupart des requêtes nécessitent un Header `Authorization: Bearer {{ access_token }}`. N'oubliez pas de mettre à jour la variable après le login.
