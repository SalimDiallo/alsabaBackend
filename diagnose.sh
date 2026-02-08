#!/bin/bash
# Script de diagnostic pour les conteneurs qui redémarrent

echo "🔍 Diagnostic des conteneurs en redémarrage"
echo "==========================================="
echo ""

echo "📋 Logs de alsaba_django (dernières 50 lignes):"
echo "-----------------------------------------------"
sudo docker logs --tail 50 alsaba_django 2>&1 | tail -30
echo ""

echo "📋 Logs de alsaba_celery_worker (dernières 50 lignes):"
echo "------------------------------------------------------"
sudo docker logs --tail 50 alsaba_celery_worker 2>&1 | tail -30
echo ""

echo "📋 Logs de alsaba_celery_beat (dernières 50 lignes):"
echo "---------------------------------------------------"
sudo docker logs --tail 50 alsaba_celery_beat 2>&1 | tail -30
echo ""

echo "💡 Pour voir les logs en temps réel:"
echo "   sudo docker-compose logs -f web"
echo "   sudo docker-compose logs -f celery_worker"
echo "   sudo docker-compose logs -f celery_beat"

