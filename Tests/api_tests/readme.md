# Tests API Django – Flux complet utilisateur

Ce dossier contient une suite de scripts Bash modulaires pour tester **l’ensemble du flux utilisateur** de ton application Django :

1. Authentification par téléphone (OTP Didit)
2. Récupération du profil
3. Vérification KYC (Didit ID Verification)
4. Profil mis à jour après KYC
5. Demande de suppression de compte
6. Confirmation de suppression (soft delete)

Les tests sont **séparés en 7 étapes** pour faciliter le debug, les tests unitaires manuels et l’automatisation future.

## Prérequis

- Django serveur lancé en local : `python manage.py runserver`
- `jq` installé (pour parser le JSON)  
  → macOS : `brew install jq`  
  → Ubuntu/Debian : `sudo apt install jq`  
  → Windows (WSL ou Git Bash) : `apt install jq` ou télécharger depuis https://stedolan.github.io/jq/
- `curl` installé (généralement présent par défaut)

## Structure des fichiers
api_tests/
├── config.sh                     # Configuration commune (URL, numéro test, chemins images)
├── 01_request_otp.sh             # Demande d'envoi OTP
├── 02_verify_otp.sh              # Vérification OTP + récupération token
├── 03_get_profile.sh             # Affichage profil initial
├── 04_kyc_verify.sh              # Vérification KYC avec upload document
├── 05_profile_after_kyc.sh       # Profil après KYC (vérifie les données extraites)
├── 06_request_delete.sh          # Demande suppression (envoi OTP de confirmation)
├── 07_confirm_delete.sh          # Confirmation suppression avec OTP

## Configuration

1. Édite le fichier `config.sh` :
nano config.sh
Modifie ces lignes :
BashTEST_PHONE="0612345678"           # ← Ton numéro réel pour recevoir les SMS
TEST_PHONE_E164="+33612345678"     # ← Même numéro au format E.164
FRONT_IMAGE="../test_images/recto.jpg"    # ← Chemin vers photo recto
BACK_IMAGE="../test_images/verso.jpg"     # ← Chemin vers photo verso (optionnel)

2. Crée le dossier test_images/ à la racine du projet et place-y tes photos de test :

textproject/
├── test_images/
│   ├── recto.jpg
│   └── verso.jpg
├── api_tests/
└── manage.py

3. Entre dans le dossier :
cd api_tests
Puis lance les scripts dans l’ordre :
./01_request_otp.sh
./02_verify_otp.sh          # ← Saisis le code OTP reçu par SMS
./03_get_profile.sh
./04_kyc_verify.sh          # ← Envoi du document KYC
./05_profile_after_kyc.sh
./06_request_delete.sh      # ← Demande suppression
./07_confirm_delete.sh      # ← Saisis le code OTP de confirmation