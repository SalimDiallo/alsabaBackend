#!/bin/bash
# Script pour corriger le problème de conteneurs Docker corrompus

echo "🔧 Correction des conteneurs Docker corrompus"
echo "============================================"
echo ""

echo "1. Arrêt de tous les services..."
sudo docker-compose down

echo ""
echo "2. Suppression des conteneurs orphelins..."
# Supprimer tous les conteneurs arrêtés
sudo docker container prune -f

echo ""
echo "3. Suppression des conteneurs problématiques spécifiques..."
# Supprimer les conteneurs Django/Celery s'ils existent encore
sudo docker rm -f alsaba_django alsaba_celery_worker alsaba_celery_beat 2>/dev/null || true

# Supprimer les conteneurs par ID si nécessaire
sudo docker ps -a | grep -E "feb4db9d4aad|9d58ff34900f" | awk '{print $1}' | xargs -r sudo docker rm -f 2>/dev/null || true

echo ""
echo "4. Nettoyage des images orphelines..."
sudo docker image prune -f

echo ""
echo "5. Reconstruction et démarrage..."
sudo docker-compose up -d --build --force-recreate

echo ""
echo "6. Vérification de l'état..."
sleep 3
sudo docker-compose ps

echo ""
echo "✅ Correction terminée !"

