#!/bin/bash
# Script pour redémarrer les services après correction

echo "🔄 Redémarrage des services..."
echo ""

# Arrêter les services
echo "1. Arrêt des services..."
sudo docker-compose down

# Reconstruire les images (pour prendre en compte les changements du script)
echo ""
echo "2. Reconstruction des images..."
sudo docker-compose build

# Redémarrer les services
echo ""
echo "3. Démarrage des services..."
sudo docker-compose up -d

# Attendre quelques secondes
sleep 5

# Vérifier l'état
echo ""
echo "4. État des services:"
sudo docker-compose ps

echo ""
echo "✅ Redémarrage terminé !"
echo ""
echo "📋 Pour voir les logs:"
echo "   sudo docker-compose logs -f web"
echo "   sudo docker-compose logs -f celery_worker"
echo "   sudo docker-compose logs -f celery_beat"

