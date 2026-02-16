# 🔔 Firebase Cloud Messaging - Instructions Rapides

## ⚡ Étapes pour activer FCM

### 1. Créer le fichier de credentials Firebase

1. **Aller sur Firebase Console** : https://console.firebase.google.com/
2. **Créer/Sélectionner votre projet** : `ALSABA`
3. **Paramètres du projet** (⚙️) → **Comptes de service**
4. **Générer une nouvelle clé privée** → Télécharger le fichier JSON
5. **Renommer le fichier** : `firebase-credentials.json`
6. **Placer le fichier ici** : `c:\Users\HP\Desktop\APPLICATION\Project\firebase-credentials.json`

### 2. Redémarrer Docker

```bash
cd c:\Users\HP\Desktop\APPLICATION
docker-compose down
docker-compose up -d
```

### 3. Tester FCM

```bash
# Accéder au shell Django
docker-compose exec web python manage.py shell

# Tester l'initialisation
from Notifications.tasks import _get_firebase_app
app = _get_firebase_app()
print(app)  # Doit afficher un objet Firebase App
```

## ✅ Checklist

- [ ] Projet Firebase créé
- [ ] Fichier `firebase-credentials.json` téléchargé
- [ ] Fichier placé dans `Project/firebase-credentials.json`
- [ ] Variable `GOOGLE_APPLICATION_CREDENTIALS` déjà ajoutée dans `.env` ✅
- [ ] Docker redémarré
- [ ] Test d'initialisation réussi

## 📚 Documentation complète

Pour plus de détails, consultez le guide complet : `fcm_setup_guide.md`

## 🆘 En cas de problème

```bash
# Vérifier les logs
docker-compose logs -f celery_worker | grep firebase

# Vérifier que le fichier est accessible dans le conteneur
docker-compose exec web ls -la /app/Project/firebase-credentials.json
```
