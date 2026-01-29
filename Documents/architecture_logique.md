# Architecture Logique du Projet ALSABA

Voici le diagramme logique illustrant le flux complet d'une transaction, depuis l'inscription jusqu'à l'échange P2P final (Hawala).

```mermaid
sequenceDiagram
    autonumber
    
    actor A1 as User A1 (Sénégal)
    participant Auth as Auth (Didit)
    participant Wallet as Wallet Service
    participant Offer as Offer Service (Escrow)
    participant B1 as Wallet B1 (Ami de A2)
    
    %% Phase 1: Onboarding
    Note over A1, Auth: 1. Authenticaton & KYC
    A1->>Auth: POST /auth/phone/ (Send SMS)
    A1->>Auth: POST /auth/verify/ (Verify OTP)
    Auth->>Wallet: Create Wallet (XOF)
    A1->>Auth: POST /kyc/verify/ (Upload ID)
    Auth-->>A1: Status: VERIFIED

    %% Phase 2: Dépôt (Deposit)
    Note over A1, Wallet: 2. Chargement du Wallet
    A1->>Wallet: POST /wallet/deposit/ (100k XOF, Orange Money)
    Wallet->>Flutterwave: Initiate Charge
    Flutterwave-->>Wallet: Webhook (Success)
    Wallet->>Wallet: Credit 100k XOF (Solde Réel)

    %% Phase 3: Création Offre
    Note over A1, Offer: 3. Mise en vente
    A1->>Offer: POST /api/offers/create/
    Note right of A1: "Je vends 100k XOF contre 150 EUR"<br/>Bénéficiaire EUR: B2 (Ami en France)
    Offer-->>A1: Offer OPEN

    %% Phase 4: Acceptation & Escrow (Lock)
    actor A2 as User A2 (France)
    participant B2 as Wallet B2 (Ami de A1)
    
    Note over A2, Offer: 4. Matching & Locking
    A2->>Wallet: POST /wallet/deposit/ (150 EUR, Carte)
    A2->>Offer: GET /api/offers/ (Trouve l'offre)
    A2->>Offer: POST /api/offers/{id}/accept/
    Note right of A2: "J'accepte"<br/>Bénéficiaire XOF: B1 (Ami au Sénégal)
    
    rect rgb(255, 240, 240)
        Note right of Offer: SECURE ESCROW
        Offer->>Wallet: LOCK 100k XOF (Account A1)
        Offer->>Wallet: LOCK 150 EUR (Account A2)
        Offer-->>A1: Notification (Locked)
        Offer-->>A2: Notification (Locked)
    end

    %% Phase 5: Settlement (Confirm)
    Note over A1, B2: 5. Exécution (Hawala Swap)
    A1->>Offer: POST /api/offers/{id}/confirm/
    
    Offer->>Wallet: DEBIT Locked XOF (A1)
    Wallet->>B1: CREDIT 100k XOF (Wallet B1)
    
    Offer->>Wallet: DEBIT Locked EUR (A2)
    Wallet->>B2: CREDIT 150 EUR (Wallet B2)
    
    Offer-->>A1: Transaction COMPLETED
    Offer-->>A2: Transaction COMPLETED

    %% Phase 6: Retrait
    Note over B1: 6. Sortie des fonds
    B1->>Wallet: POST /wallet/withdraw/ (Orange Money)
    B2->>Wallet: POST /wallet/withdraw/ (Virement SEPA)
```

## Légende des Endpoints Clés

| Phase | Endpoint | Description |
| :--- | :--- | :--- |
| **Auth** | `/api/accounts/auth/verify/` | Connexion & Token JWT |
| **Wallet** | `/api/wallet/deposit/` | Charger de l'argent réel dans le système |
| **Offer** | `/api/offers/create/` | Créer une annonce |
| **Offer** | `/api/offers/{id}/accept/` | **CRITIQUE** : Verrouille les fonds (Escrow) |
| **Offer** | `/api/offers/{id}/confirm/` | **CRITIQUE** : Exécute le swap vers les bénéficiaires |
| **Wallet** | `/api/wallet/withdraw/` | Récupérer l'argent vers le monde réel |
