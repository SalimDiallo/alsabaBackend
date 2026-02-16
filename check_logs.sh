#!/bin/bash
# Script pour vérifier les logs des conteneurs

echo "🔍 Vérification des logs - Django"
echo "=================================="
sudo docker logs alsaba_django --tail 50 2>&1

echo ""
echo "🔍 Vérification des logs - Celery Worker"
echo "========================================="
sudo docker logs alsaba_celery_worker --tail 50 2>&1

echo ""
echo "🔍 Vérification des logs - Celery Beat"
echo "======================================="
sudo docker logs alsaba_celery_beat --tail 50 2>&1

