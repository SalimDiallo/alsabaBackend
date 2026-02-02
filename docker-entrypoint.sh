#!/bin/bash

# ===================================
# Script d'entrée Docker pour Django
# ===================================

set -e

echo "🔄 Attente de la base de données PostgreSQL..."

# Variables avec fallback
HOST=${DATABASE_HOST:-db}
PORT=${DATABASE_PORT:-5432}
USER=${DATABASE_USER:-alsaba_user}

# Attente fiable avec pg_isready (beaucoup mieux que nc)
until pg_isready -h "$HOST" -p "$PORT" -U "$USER"; do
    echo "⏳ PostgreSQL n'est pas encore prêt ($HOST:$PORT) - attente 2s..."
    sleep 2
done

echo "✅ PostgreSQL est prêt !"

# Application des migrations seulement si demandé
if [ "$RUN_MIGRATIONS" = "True" ]; then
    echo "🔄 Application des migrations..."
    python manage.py migrate --noinput
fi

# Collection des fichiers statiques seulement si DEBUG=False (production)
if [ "$DEBUG" = "False" ]; then
    echo "📦 Collection des fichiers statiques..."
    python manage.py collectstatic --noinput --clear
fi

echo "🚀 Démarrage du serveur Django..."

# Exécute la commande passée (runserver par défaut)
exec "$@"