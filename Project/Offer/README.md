# Offer App - Guide de Test des Endpoints (P2P Exchange)

Ce module gère le cœur de l'échange P2P sécurisé.

## 🔄 Cycle de Vie d'une Offre
1.  **OPEN** : Créée par A (Vendeur), visible par tous.
2.  **ACCEPTED** : B (Acheteur) accepte l'offre. Les fonds de B sont vérifiés/pré-bloqués.
3.  **LOCKED** : A valide l'acceptation de B. Les fonds des DEUX parties sont bloqués en Escrow.
4.  **COMPLETED** : L'échange (Swap) est exécuté.

---

## 1. Gestion des Offres

### Créer une offre (Utilisateur A)
Je vends des XOF pour recevoir des EUR.
*   **Endpoint** : `POST /api/offers/create/`
*   **Body** :
    ```json
    {
        "amount_sell": 100,
        "currency_sell": "XOF",
        "amount_buy": 10,
        "currency_buy": "EUR",
        "expiry_hours": 24,
        "beneficiary_name": "Mon Compte EUR", // Optionnel ici, peut être mis à la validation
        "beneficiary_phone": "+33..."
    }
    ```

### Lister les offres disponibles
Pour qu'un utilisateur B trouve une offre.
*   **Endpoint** : `GET /api/offers/`

---

## 2. Flux d'Échange (The Swap)

### Étape A : Accepter une offre (Utilisateur B)
B arrive, voit l'offre de A et l'accepte. B indique où il veut recevoir ses XOF (le `beneficiary_data` pour le `currency_sell` de l'offre).
*   **Endpoint** : `POST /api/offers/<uuid_offre>/accept/`
*   **Header** : `Authorization: Bearer <token_USER_B>`
*   **Body** :
    ```json
    {
        "beneficiary_name": "Moi B",
        "beneficiary_phone": "+225..." // Là où B veut recevoir les XOF
    }
    ```
*   *État : ACCEPTED*

### Étape B : Valider l'échange (Utilisateur A)
A reçoit une notif, voit que B a accepté. A valide et confirme ses propres infos de réception (pour recevoir les EUR de B).
*   **Endpoint** : `POST /api/offers/<uuid_offre>/validate/`
*   **Header** : `Authorization: Bearer <token_USER_A>`
*   **Body** :
    ```json
    {
        "beneficiary_name": "Moi A",
        "beneficiary_phone": "+33..." // Là où A veut recevoir les EUR
    }
    ```
*   *État : LOCKED (Fonds bloqués)*

### Étape C : Confirmer & Exécuter (Automatique ou A/Admin)
Déclenche le transfert des fonds bloqués vers les bénéficiaires respectifs.
*   **Endpoint** : `POST /api/offers/<uuid_offre>/confirm/`

---

## 3. Litiges (Disputes)

Si quelque chose se passe mal (ex: fonds bloqués mais pas reçus).

### Ouvrir un litige
*   **Endpoint** : `POST /api/offers/<uuid_offre>/disputes/`
*   **Body** : `{"reason": "...", "evidence": {...}}`

### Lister mes litiges
*   **Endpoint** : `GET /api/offers/disputes/`

### Détail d'un litige
*   **Endpoint** : `GET /api/offers/disputes/<uuid_litige>/`
