# Configuration — ce qu'il reste à remplir

Tout le câblage est fait : chaque variable de `.env` atteint désormais les
conteneurs qui en ont besoin. Il ne reste qu'à **coller des valeurs**.

Rappel important : `.env` vit à la racine du dépôt, mais seul `Project/` est monté
dans les conteneurs. Django ne lit donc **pas** `.env` en Docker — c'est
`docker-compose.yml` qui transmet les variables. Toute nouvelle variable doit être
ajoutée aux **deux** endroits.

---

## 1. À aller chercher (bloquant pour la production)

### SMTP — confirmations de dépôt et de retrait
Sans `EMAIL_HOST`, `settings.py` **refuse de démarrer** avec `DEBUG=False`.

```
EMAIL_HOST=
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=noreply@<ton-domaine>
```

Fournisseur conseillé : Brevo (relais SMTP, palier gratuit). Il faut aussi
publier **SPF, DKIM et DMARC** sur le domaine, sinon les confirmations de retrait
partent en spam.

### Sentry — monitoring
Créer un projet Django sur sentry.io, puis *Settings → Projects → Client Keys (DSN)*.

```
SENTRY_DSN=
ENVIRONMENT=production
SENTRY_FORCED=False
```

---

## 2. Placeholders encore en place dans `.env`

| Variable | Valeur actuelle | À remplacer par |
|---|---|---|
| `ALLOWED_HOSTS` | `api.votredomaine.com,...` | tes vrais domaines |
| `CORS_ALLOWED_ORIGINS` | `https://votredomaine.com` | l'origine du front |
| `FLUTTERWAVE_REDIRECT_URL` | `https://votredomaine.com/redirect` | l'URL réelle de retour après paiement |
| `FLOWER_BASIC_AUTH` | `admin:changeme` | un vrai couple utilisateur/mot de passe |
| `ALERT_WEBHOOK_URL` | vide | URL entrante Slack/Discord (alertes d'échec de backup) |

---

## 2 bis. Déploiement production

La stack de prod est une **surcouche** du compose de dev :

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Elle change : `daphne` au lieu de `runserver`, nginx en frontal (TLS + fichiers
statiques + WebSocket), plus aucun code monté en volume, ports PostgreSQL et
Redis fermés, `DEBUG=False`.

Les outils de dev (**pgAdmin, ngrok, Flower**) ne démarrent plus par défaut,
même en dev. Pour les lancer :

```bash
docker compose --profile tools up -d
```

### Certificats TLS

Déposer `fullchain.pem` et `privkey.pem` dans `docker/nginx/certs/`
(le dossier est ignoré par git). En production, les obtenir via Let's Encrypt.
Pour un test local, un certificat auto-signé suffit :

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout docker/nginx/certs/privkey.pem -out docker/nginx/certs/fullchain.pem -subj "/CN=localhost"
```

Renseigner aussi `NGINX_SERVER_NAME` dans `.env` (le domaine servi).

---

## 3. Avant de basculer en production

- [ ] `DEBUG=False` (aujourd'hui `True`)
- [ ] `FLUTTERWAVE_ENVIRONMENT=production` — la valeur est désormais validée au
      démarrage : toute autre chaîne que `sandbox` ou `production` fait échouer
      le boot au lieu de basculer en sandbox silencieusement
- [ ] Renseigner `FLUTTERWAVE_PRODUCTION_CLIENT_ID` / `_CLIENT_SECRET`
      (exigés au démarrage quand l'environnement vaut `production`)
- [ ] Vérifier que `Project/firebase-credentials.json` est présent sur le serveur
      (il est monté en lecture seule, et volontairement **exclu de l'image**)
- [ ] Déposer les certificats TLS et renseigner `NGINX_SERVER_NAME`
- [ ] **Tester une restauration de backup** — un backup jamais restauré n'est pas
      un backup, et il s'agit d'une base de soldes

### ⚠️ `KYC_ENCRYPTION_KEY` — à lire avant toute rotation de secret

Les documents d'identité sont chiffrés avec une clé dérivée de
`KYC_ENCRYPTION_KEY`, ou de `SECRET_KEY` si elle est vide.

**Changer cette clé rend tous les documents déjà stockés définitivement
illisibles.** Aucune récupération possible.

Renseigne `KYC_ENCRYPTION_KEY` avec une valeur dédiée **avant** d'avoir de vrais
utilisateurs : tu pourras ensuite faire tourner `SECRET_KEY` (rotation de
sécurité normale) sans détruire les données KYC. Si tu la laisses vide, les deux
secrets restent liés à vie.

---

## 4. Vérifier que ça marche

Après `docker compose up -d --build` :

```bash
docker compose logs celery_worker | grep -i "firebase_credentials_missing"
```

Aucune sortie = les notifications push sont opérationnelles.

```bash
curl -s localhost:8000/ready/
```

Doit renvoyer `{"status": "ok", ...}` avec `database`, `cache` et `celery` à `ok`.

Test d'envoi d'email réel :

```bash
docker compose exec web python -c "from django.core.mail import send_mail; send_mail('test','ok',None,['toi@exemple.com'])"
```

Vérification Sentry (avec `SENTRY_FORCED=True`) :

```bash
docker compose exec web python -c "import sentry_sdk; sentry_sdk.capture_message('test alsaba')"
```
