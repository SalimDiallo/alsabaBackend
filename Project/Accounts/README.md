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
Initialise une session KYC avec Didit.

*   **Endpoint** : `POST /api/accounts/kyc/verify/`
*   **Header** : `Authorization: Bearer <votre_token>`
*   **Body** : (Vide ou spécifiant le type de document si demandé, sinon géré par le SDK frontend)
    ```json
    {}
    ```
*   **Réponse** : URL de redirection Didit ou session ID.

### Webhook (Simulation)
Didit appelle cette URL quand le KYC est fini.
*   **Endpoint** : `POST /api/accounts/webhooks/didit/kyc/`
*   **Note** : Ce endpoint est public mais protégé par signature (ou secret en local).

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
