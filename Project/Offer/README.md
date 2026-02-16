# Offer App - Endpoint Testing Guide (P2P Exchange)

This module manages the core of the secure P2P exchange.

## 🔄 Offer Lifecycle
1.  **OPEN**: Created by A (Seller), visible to all.
2.  **ACCEPTED**: B (Buyer) accepts the offer. B's funds are verified/pre-blocked.
3.  **LOCKED**: A validates B's acceptance. Funds from BOTH parties are blocked in Escrow.
4.  **COMPLETED**: The exchange (Swap) is executed.

---

## 1. Offer Management

### Create an offer (User A)
I sell XOF to receive EUR.
*   **Endpoint**: `POST /api/offers/create/`
*   **Body**:
    ```json
    {
        "amount_sell": 100,
        "currency_sell": "XOF",
        "amount_buy": 10,
        "currency_buy": "EUR",
        "expiry_hours": 24,
        "beneficiary_name": "My EUR Account", // Optional here, can be set during validation
        "beneficiary_phone": "+33..."
    }
    ```

### List available offers (All)
*   **Endpoint**: `GET /api/offers/`

### List foreign offers (Filtered)
*   **Endpoint**: `GET /api/offers/foreign/`
*   **Query Filters**: `currency_sell`, `currency_buy`, `min_amount`, `max_amount`.
*   **Logic**: Automatically excludes offers from your own country.

---

## 2. Exchange Flow (The Swap)

### Step A: Accept an offer (User B)
B arrives, sees A's offer and accepts it. B indicates where he wants to receive his XOF (the `beneficiary_data` for the `currency_sell` of the offer).
*   **Endpoint**: `POST /api/offers/<uuid_offre>/accept/`
*   **Header**: `Authorization: Bearer <token_USER_B>`
*   **Body**:
    ```json
    {
        "beneficiary_name": "Me B",
        "beneficiary_phone": "+225..." // Where B wants to receive the XOF
    }
    ```
*   *State: ACCEPTED*

### Step B: Validate the exchange (User A)
A receives a notification, sees that B has accepted. A validates and confirms his own reception info (to receive EUR from B).
*   **Endpoint**: `POST /api/offers/<uuid_offre>/validate/`
*   **Header**: `Authorization: Bearer <token_USER_A>`
*   **Body**:
    ```json
    {
        "beneficiary_name": "Me A",
        "beneficiary_phone": "+33..." // Where A wants to receive the EUR
    }
    ```
*   *State: LOCKED (Blocked funds)*

### Step C: Confirm & Execute (Automatic or A/Admin)
Triggers the transfer of blocked funds to respective beneficiaries.
*   **Endpoint**: `POST /api/offers/<uuid_offre>/confirm/`

---

## 3. Disputes

If something goes wrong (e.g., funds blocked but not received).

### Open a dispute
*   **Endpoint**: `POST /api/offers/<uuid_offre>/disputes/`
*   **Body**: `{"reason": "...", "evidence": {...}}`

### List my disputes
*   **Endpoint**: `GET /api/offers/disputes/`

### Dispute detail
*   **Endpoint**: `GET /api/offers/disputes/<uuid_dispute>/`
