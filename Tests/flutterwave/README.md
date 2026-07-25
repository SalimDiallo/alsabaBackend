# Scripts manuels Flutterwave

Ce ne sont **pas** des tests automatisés : aucune assertion, pas collectés par
pytest, non exécutés par la CI. Ce sont des scripts d'appel manuel contre le
sandbox Flutterwave, utiles pour reproduire un paiement à la main quand on
débogue l'intégration.

La suite de tests réelle vit dans `Project/*/tests/` et se lance avec `pytest`.

Exécution :

```bash
cd Tests/flutterwave
python flutterwave_card.py
```

Les identifiants sont lus depuis `config.py` — ne pas y committer de clés de
production.
