# 🧪 Guide de Test Alsaba API (Insomnia)

Ce dossier contient la collection Insomnia pour tester l'intégralité des **42 endpoints** de l'API Alsaba. Pour un test cohérent, suivez l'ordre logique ci-dessous.

---

## 🔐 Phase 1 : Authentification & JWT (5 endpoints)
*Indispensable pour toutes les autres requêtes.*

1.  **Auth: 1. Phone Auth** : Envoie un OTP (simulé ou réel). Récupérez la `session_key`.
2.  **Auth: 2. Verify OTP** : Utilisez la `session_key` et le code (ex: `123456`). Récupérez les tokens `access` et `refresh`.
3.  **Auth: Refresh JWT** : Renouvelle l'access token.

---

## 👤 Phase 2 : Profil & KYC (6 endpoints)
*Nécessaire pour lever les limites du compte.*

1.  **Profile: View/Update** : Voir et modifier vos informations.
2.  **KYC: Submit Verification** : Envoyez vos photos de documents.
3.  **Webhook: Didit KYC** : Simulez l'approbation de votre KYC par le service tiers.
4.  **Account: Delete (Request/Confirm)** : Cycle de suppression.

---

## 💰 Phase 3 : Wallet & Méthodes de Paiement (14 endpoints)
*Préparez votre solde avant de faire du P2P.*

1.  **Wallet: PM (List/Create/Detail/Delete/Default)** : Gérez vos comptes Orange Money ou cartes.
2.  **Wallet: Deposit Initiate** : Initiez un dépôt.
3.  **Webhook: Flutterwave** : Simulez le paiement réussi.
4.  **Wallet: Transactions (List/Detail/Status/Retry)** : Suivi précis des mouvements.

---

## 🤝 Phase 4 : Le Flux P2P (Escrow) (10 endpoints)
*Nécessite deux utilisateurs (A et B).*

1.  **Offer: Create** : Le vendeur A bloque ses fonds.
2.  **Offer: List/Detail/Update** : Gestion des annonces.
3.  **Offer: Accept (Buyer)** : L'acheteur B se manifeste.
4.  **Offer: Validate (Seller)** : Le vendeur A confirme le matching.
5.  **Offer: Confirm/Cancel/Dispute** : Déblocage, annulation ou litige.

---

## 💡 Phase 5 : Suggestions ML (2 endpoints)
1.  **Suggestions: List** : Matching intelligent basé sur le profil.
2.  **Suggestions: Mark Read** : Nettoyer ses notifications.

---

## 🛡️ Phase 6 : Administration Staff (5 endpoints)
*Nécessite un accès `is_staff`.*

1.  **Wallet: Admin Stats** : Santé globale du système.
2.  **Wallet: Admin Deposit/Withdrawal (Confirm/Cancel)** : Validation manuelle forcée par l'admin.
3.  **Wallet: Admin Update Status** : Correction manuelle de statut de transaction.
