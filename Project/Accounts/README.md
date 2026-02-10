# Accounts App - Guide de Test des Endpoints

Ce document détaille l'ordre logique et les payloads pour tester les fonctionnalités d'authentification et de gestion de compte.

## 1. Authentification (Login / Register)

Le flux est le même pour l'inscription et la connexion.

### Étape 1 : Demander un code OTP
Envoie un SMS à l'utilisateur.

*   **Endpoint** : `POST /api/accounts/auth/phone/`
*   **Body** :
    ```json
    {
        "phone_number": "+33612345678",
        "country_code": "+33"
    }
    ```
*   **Réponse attendue** : `200 OK` avec `session_key` et `request_id`.

### Étape 2 : Vérifier le code OTP
Valide le code reçu et retourne les tokens d'accès.

*   **Endpoint** : `POST /api/accounts/auth/verify/`
*   **Body** :
    ```json
    {
        "phone_number": "+33612345678",
        "code": "123456",
        "session_key": "auth_..."  // Reçu à l'étape 1
    }
    ```
*   **Réponse attendue** : `200 OK` avec `access` (Token JWT) et `refresh`.
    *   *Note : Conservez le `access` token (Bearer) pour toutes les requêtes suivantes.*

---

## 2. Gestion du Profil

Une fois authentifié.

### Voir/Modifier le profil
*   **Endpoint** : `GET` ou `PUT /api/accounts/profile/`
*   **Header** : `Authorization: Bearer <votre_token>`
*   **Body (PUT)** :
    ```json
    {
        "first_name": "Jean",
        "last_name": "Dupont",
        "email": "jean@example.com"
    }
    ```

---

## 3. Vérification d'Identité (KYC)

Nécessaire pour faire des transactions.

### Soumettre une vérification
Initialise ou soumet une session KYC avec Didit v3.

*   **Endpoint** : `POST /api/accounts/kyc/verify/`
*   **Header** : `Authorization: Bearer <votre_token>`
*   **Body (Multipart)** : 
    - `document_type` : (ex: `passport`, `id_card`)
    - `front_image` : (Fichier)
    - `back_image` : (Fichier - Optionnel pour passeports)
    - `selfie_image` : (Fichier - **Requis pour le Face Match**)
*   **Logique** : Réalise une extraction OCR et un Face Match biométrique.

### Webhook
Didit appelle cette URL quand le KYC est terminé.
*   **Endpoint** : `POST /api/accounts/webhooks/didit/kyc/`
*   **Sécurité** : Vérification obligatoire des headers `X-Signature` et `X-Timestamp`.

---

## 4. Suppression de Compte

### Étape 1 : Demande de suppression
Envoie un OTP de confirmation.
*   **Endpoint** : `POST /api/accounts/delete/`
*   **Header** : `Authorization: Bearer <votre_token>`

### Étape 2 : Confirmation
*   **Endpoint** : `POST /api/accounts/delete/confirm/`
*   **Body** :
    ```json
    {
        "code": "123456",
        "session_key": "delete_..."
    }
    ```
