# Wallet App - Guide de Test des Endpoints

Ce module gère les fonds, les dépôts et les retraits via Flutterwave.

## 1. Informations Portefeuille

### Consulter le solde
*   **Endpoint** : `GET /api/wallet/`
*   **Header** : `Authorization: Bearer <votre_token>`
*   **Réponse** : Solde actuel, devise, etc.

---

## 2. Dépôt (Deposit)

Pour ajouter des fonds via Mobile Money ou Carte.

### Initier un dépôt
*   **Endpoint** : `POST /api/wallet/deposit/`
*   **Body** :
    ```json
    {
        "amount": 5000,
        "currency": "XOF",  // ou EUR, USD...
        "payment_method": "mobile_money", // ou "card"
        "phone_number": "0612345678" // Requis pour Mobile Money
    }
    ```
*   **Réponse** : Un lien de paiement Flutterwave (`payment_link`) ou une instruction.

### Simulation Webhook (Callback)
Pour valider le dépôt en local sans payer réellement (si en mode test).
*   **Endpoint** : `POST /api/wallet/webhook/`
*   **Body (Exemple Flutterwave)** :
    ```json
    {
        "event": "charge.completed",
        "data": {
            "id": 123456,
            "tx_ref": "TX_...", // Le tx_ref retourné à l'initiation
            "flw_ref": "FLW_...",
            "amount": 5000,
            "currency": "XOF",
            "status": "successful"
        }
    }
    ```

---

## 3. Retrait (Withdrawal)

Pour récupérer des fonds vers un compte bancaire ou Mobile Money.

### Demander un retrait
*   **Endpoint** : `POST /api/wallet/withdraw/`
*   **Body** :
    ```json
    {
        "amount": 1000,
        "currency": "XOF",
        "beneficiary_account": "0612345678",
        "beneficiary_bank": "ORANGE_MONEY" // Code banque/opérateur
    }
    ```

### Confirmer le retrait (Si requis)
Pour valider définitivement l'envoi.
*   **Endpoint** : `POST /api/wallet/withdraw/<transaction_id>/confirm/`

---

## 4. Historique

### Lister les transactions
*   **Endpoint** : `GET /api/wallet/transactions/`
*   **Filtres possibles** : `?type=deposit`, `?status=completed`

### Détail d'une transaction
*   **Endpoint** : `GET /api/wallet/transactions/<transaction_id>/`
