#!/bin/bash

# ===================================
# Script d'entrée Docker pour Django
# ===================================

set -e

echo "🔄 Attente de la base de données PostgreSQL..."

# Attendre que PostgreSQL soit prêt
while ! nc -z ${DATABASE_HOST:-db} ${DATABASE_PORT:-5432}; do
    echo "⏳ PostgreSQL n'est pas encore prêt - attente..."
    sleep 2
done

echo "✅ PostgreSQL est prêt!"

# Appliquer les migrations
echo "🔄 Application des migrations..."
python manage.py migrate --noinput

# Collecter les fichiers statiques (si en production)
if [ "$DEBUG" = "False" ]; then
    echo "📦 Collection des fichiers statiques..."
    python manage.py collectstatic --noinput
fi

echo "🚀 Démarrage du serveur Django..."

# Exécuter la commande passée en argument
exec "$@"
