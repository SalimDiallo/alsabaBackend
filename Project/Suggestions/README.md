# Suggestions App - Guide de Test

Ce module fournit des recommandations basées sur l'IA (Historique, préférences).

## 1. Lister les suggestions
Récupère les offres recommandées pour l'utilisateur connecté.
*   **Endpoint** : `GET /api/suggestions/`
*   **Header** : `Authorization: Bearer <token>`
*   **Réponse** : Liste d'offres "suggérées" (avec un score de pertinence si implémenté).

## 2. Marquer comme lu
Pour ne plus voir une suggestion spécifique.
*   **Endpoint** : `POST /api/suggestions/<uuid_suggestion>/read/`
