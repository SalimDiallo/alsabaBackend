# Moteur de recommandation d'offres — ALSABA

Système unifié (flux temps réel + notifications push) de recommandation d'offres P2P,
avec **scoring explicable et configurable**.

---

## 1. Principe métier

Modèle escrow, **wallet mono-devise** :
- Pour *accepter* une offre, le preneur verrouille `amount_buy` en `currency_buy`.
- ⇒ Il doit détenir un wallet en `currency_buy` (**compatibilité devise = filtre dur**)
  et un solde suffisant (**faisabilité**).
- Le corridor du preneur est le **réciproque** de l'offre : il vend `currency_buy`
  et achète `currency_sell` → clé de corridor `"currency_buy>currency_sell"`.
- Taux vu par le preneur : `amount_sell / amount_buy` (unités de `currency_sell`
  par unité de `currency_buy`). Plus il est élevé vs le marché, meilleure est l'affaire.

---

## 2. Score (0–100)

```
score = ( Σ (sous_score_i × poids_i) / Σ poids_i ) × facteur_faisabilité × 100
```

| Sous-score | Poids | Description |
|------------|:-----:|-------------|
| `corridor_affinity`    | 0.30 | Fréquence/volume historiques du preneur sur ce corridor (saturation log) |
| `rate_competitiveness` | 0.30 | Avantage du taux vs marché (sigmoïde centrée sur le taux marché) |
| `amount_fit`           | 0.15 | Proximité du montant à engager vs habitude du preneur |
| `reputation`           | 0.15 | KYC vérifié + complétions − litiges du **créateur** |
| `freshness`            | 0.10 | Récence (demi-vie 12 h) + distance à l'expiration |

**Facteurs (hors somme pondérée) :**
- `currency_compatible` : filtre **dur** (0 sinon → offre exclue).
- `affordability` : `1.0` si solde suffisant, sinon pénalité (`0.35`).

Chaque score renvoie aussi un **breakdown** et des **raisons** lisibles (explicabilité).

Poids et seuils **configurables** via `settings` / `.env` :
`RECO_W_CORRIDOR`, `RECO_W_RATE`, `RECO_W_AMOUNT`, `RECO_W_REPUTATION`,
`RECO_W_FRESHNESS`, `RECOMMENDATION_NOTIFY_THRESHOLD` (défaut 62),
`RECOMMENDATION_MAX_CANDIDATES`, `RECOMMENDATION_FEED_CANDIDATES`.

---

## 3. Composants

| Fichier | Rôle |
|---------|------|
| `Suggestions/recommendation_engine.py` | Moteur : `score_offer`, `rank_offers_for_user`, contextes (unitaire + **bulk**) |
| `Suggestions/services.py` | `MatchingEngine` (push) + `UserPreferenceService` (apprentissage) |
| `Suggestions/tasks.py` | `match_new_offer_task` (Celery, matching **asynchrone** en prod) |
| `Suggestions/signals.py` | Offre OPEN → matching (via `on_commit`) ; COMPLETED → apprentissage ; Dispute → réputation |
| `Suggestions/views.py` | `RecommendationFeedView` (flux "Pour Vous") |
| `Suggestions/models.py` | `UserPreference` enrichi : `corridor_stats`, `completed_offers_count`, `disputes_count` |

**Apprentissage** : à chaque offre `COMPLETED`, `corridor_stats` s'incrémente
(count + volume + last_at) pour les deux parties, ainsi que le montant moyen et le
compteur de complétions. Les litiges incrémentent `disputes_count` (impact réputation).

---

## 4. API

### Flux "Pour Vous" (pull, temps réel)
```
GET /api/suggestions/feed/?limit=20&include_unaffordable=true
Authorization: Bearer <access>
```
Réponse :
```json
{
  "success": true,
  "count": 1,
  "results": [
    {
      "id": "…", "amount_sell": 500.0, "currency_sell": "XOF",
      "amount_buy": 100.0, "currency_buy": "EUR", "rate": "…", "user": {…},
      "recommendation": {
        "score": 78,
        "feasible": true,
        "affordable": true,
        "breakdown": {"corridor_affinity": 0.75, "rate_competitiveness": 0.88, …},
        "reasons": ["Solde suffisant pour accepter", "Taux avantageux (+7.5% vs marché)", …]
      }
    }
  ]
}
```

### Notifications push (matching à la création d'offre)
Automatique : à la création d'une offre OPEN, `match_new_offer_task` note les preneurs
compatibles (bonne devise) et notifie ceux **finançables** au-dessus du seuil.
Le payload de la notification inclut `score`, `breakdown` et `reasons`.

---

## 5. Performance & robustesse

- **Filtre devise en base** : la présélection ne charge que les offres/preneurs dans la
  bonne devise (réduit fortement l'espace de candidats).
- **Contexte bulk** : réputation/solde/préférences des candidats en 2 requêtes (push).
- **Cache** : taux marché (Redis, 1 h) et profils créateurs mis en cache dans le classement.
- **Async** : matching offloadé à Celery via `transaction.on_commit` (ne bloque pas la
  création d'offre, évite de matcher une offre rollback).

> Note : l'ancien `AdvancedMLEngine` (KNN sur joblib disque, fragile/non explicable) n'est
> plus dans le chemin critique. Il peut être réintroduit plus tard comme signal
> collaboratif additif si besoin.

---

## 6. Tests (`Suggestions/tests/test_recommendation.py`) — 8 tests

- Compatibilité devise (filtre dur), faisabilité (solde insuffisant)
- Compétitivité du taux (offre > marché mieux notée)
- Affinité corridor (historique booste le score)
- Apprentissage (`corridor_stats` alimenté)
- Feed (classe seulement les offres finançables, exclut les incompatibles/siennes)
- Push matching (notifie un preneur pertinent ; ignore les devises incompatibles)

```bash
docker exec alsaba_django sh -c "cd /app && pytest Suggestions/tests -v"
```

État : **8/8 verts** · suite backend globale **39/39** · endpoint feed vérifié en live (401/200).



Pistes d'amÃ©lioration possibles

- Signal collaboratif (utilisateurs aux corridors similaires) rÃ©introduit proprement (co-occurrence, sans le joblib).
- DiversitÃ©/exploration (Îµ-greedy) pour ne pas figer le feed sur un seul corridor.
- Pagination du feed + cache court par utilisateur.
- A/B testing des poids + mÃ©triques (taux d'acceptation des offres recommandÃ©es).
