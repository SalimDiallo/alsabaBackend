# Wallet App - Endpoint Testing Guide

This module manages funds, deposits, and withdrawals via Flutterwave.

## 1. Wallet Information

### Check balance
*   **Endpoint**: `GET /api/wallet/`
*   **Header**: `Authorization: Bearer <your_token>`
*   **Response**: Current balance, currency, etc.

---

## 2. Deposit

To add funds via Mobile Money or Card.

### Initiate a deposit
*   **Endpoint**: `POST /api/wallet/deposit/`
*   **Body**:
    ```json
    {
        "amount": 5000,
        "currency": "XOF",  // or EUR, USD...
        "payment_method": "mobile_money", // or "card"
        "phone_number": "0612345678" // Required for Mobile Money
    }
    ```
*   **Response**: A Flutterwave payment link (`payment_link`) or an instruction.

### Webhook Simulation (Callback)
To validate the deposit locally without actually paying (if in test mode).
*   **Endpoint**: `POST /api/wallet/webhook/`
*   **Body (Flutterwave Example)**:
    ```json
    {
        "event": "charge.completed",
        "data": {
            "id": 123456,
            "tx_ref": "TX_...", // The tx_ref returned at initiation
            "flw_ref": "FLW_...",
            "amount": 5000,
            "currency": "XOF",
            "status": "successful"
        }
    }
    ```

---

## 3. Withdrawal

To retrieve funds to a bank account or Mobile Money.

### Request a withdrawal
*   **Endpoint**: `POST /api/wallet/withdraw/`
*   **Body**:
    ```json
    {
        "amount": 1000,
        "currency": "XOF",
        "beneficiary_account": "0612345678",
        "beneficiary_bank": "ORANGE_MONEY" // Bank/operator code
    }
    ```

### Confirm withdrawal (If required)
To definitively validate the sending.
*   **Endpoint**: `POST /api/wallet/withdraw/<transaction_id>/confirm/`

---

## 4. History

### List transactions
*   **Endpoint**: `GET /api/wallet/transactions/`
*   **Possible filters**: `?type=deposit`, `?status=completed`

### Transaction detail
*   **Endpoint**: `GET /api/wallet/transactions/<transaction_id>/`
