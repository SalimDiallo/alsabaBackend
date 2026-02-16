# Notifications App - Guide de Test

Gestion des notifications Push et In-App.

## 1. Enregistrer un appareil (FCM)
Pour recevoir des notifications Push, le mobile doit envoyer son token FCM.
*   **Endpoint** : `POST /api/notifications/register-device/`
*   **Header** : `Authorization: Bearer <token>`
*   **Body** :
    ```json
    {
        "registration_id": "fcm_token_xyz...",
        "type": "android" // ou "ios"
    }
    ```

## 2. Lire les notifications
L'historique des notifications reçues.
*   **Endpoint** : `GET /api/notifications/`
*   **Réponse** : Liste paginée.

## 3. Marquer comme lue
*   **Endpoint** : `PATCH /api/notifications/<id>/`
*   **Body** : `{"unread": false}`
