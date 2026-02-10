#!/bin/bash
#
# Docker entrypoint pour le service de backup
#

set -e

echo "========================================="
echo "Service de Backup PostgreSQL - ALSABA"
echo "========================================="
echo "Démarrage à: $(date)"
echo ""

# Vérifier les variables d'environnement
if [ -z "$POSTGRES_HOST" ]; then
    echo "ERROR: POSTGRES_HOST n'est pas défini"
    exit 1
fi

if [ -z "$POSTGRES_DB" ]; then
    echo "ERROR: POSTGRES_DB n'est pas défini"
    exit 1
fi

echo "Configuration:"
echo "  Host: $POSTGRES_HOST"
echo "  Database: $POSTGRES_DB"
echo "  Backup Dir: ${BACKUP_DIR:-/backups}"
echo "  Retention: ${BACKUP_RETENTION_DAYS:-30} jours"
echo ""

# Attendre que PostgreSQL soit prêt
echo "Attente de PostgreSQL..."
until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q' 2>/dev/null; do
    echo "  PostgreSQL n'est pas encore prêt - attente..."
    sleep 2
done

echo "PostgreSQL est prêt!"
echo ""

# Effectuer un backup initial
echo "Exécution du backup initial..."
/scripts/backup.sh

echo ""
echo "Service de backup démarré avec succès"
echo "Backups programmés:"
echo "  - Quotidien: 02:00 UTC"
echo "  - Incrémental: Toutes les 6 heures"
echo "  - Monitoring: Toutes les 30 minutes"
echo "========================================="
echo ""

# Exécuter la commande passée en argument (crond par défaut)
exec "$@"
