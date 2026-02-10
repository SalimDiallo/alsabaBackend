#!/bin/bash
#
# Script de restauration PostgreSQL pour ALSABA
# Restaure une base de données depuis un backup
#
# Usage: ./restore.sh <backup_file>
#

set -e  # Arrêter en cas d'erreur
set -u  # Erreur si variable non définie

# ===================================
# CONFIGURATION
# ===================================

# Variables d'environnement
POSTGRES_DB="${POSTGRES_DB:-alsaba_db}"
POSTGRES_USER="${POSTGRES_USER:-alsaba_user}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-alsaba_password}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# Répertoire de backup
BACKUP_DIR="${BACKUP_DIR:-/backups}"

# Logging
LOG_FILE="${BACKUP_DIR}/restore.log"

# ===================================
# FONCTIONS
# ===================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

error() {
    log "ERROR: $1"
    exit 1
}

usage() {
    echo "Usage: $0 <backup_file>"
    echo ""
    echo "Exemples:"
    echo "  $0 /backups/backup_alsaba_db_20260208_020000.sql.gz"
    echo "  $0 latest  # Restaure le backup le plus récent"
    exit 1
}

check_prerequisites() {
    log "Vérification des prérequis..."
    
    # Vérifier que psql est disponible
    if ! command -v psql &> /dev/null; then
        error "psql n'est pas installé"
    fi
    
    # Vérifier que gunzip est disponible
    if ! command -v gunzip &> /dev/null; then
        error "gunzip n'est pas installé"
    fi
    
    log "Prérequis OK"
}

find_latest_backup() {
    log "Recherche du backup le plus récent..."
    
    latest=$(find "$BACKUP_DIR" -name "backup_*.sql.gz" -type f -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
    
    if [ -z "$latest" ]; then
        error "Aucun backup trouvé dans $BACKUP_DIR"
    fi
    
    echo "$latest"
}

verify_backup_file() {
    local backup_file=$1
    
    log "Vérification du fichier de backup: $backup_file"
    
    # Vérifier que le fichier existe
    if [ ! -f "$backup_file" ]; then
        error "Le fichier de backup n'existe pas: $backup_file"
    fi
    
    # Vérifier que le fichier gzip est valide
    if ! gzip -t "$backup_file" 2>> "$LOG_FILE"; then
        error "Le fichier de backup est corrompu: $backup_file"
    fi
    
    log "Fichier de backup valide (Taille: $(du -h "$backup_file" | cut -f1))"
}

create_backup_before_restore() {
    log "Création d'un backup de sécurité avant restauration..."
    
    export PGPASSWORD="$POSTGRES_PASSWORD"
    
    # Nom du backup de sécurité
    safety_backup="${BACKUP_DIR}/safety_backup_$(date +"%Y%m%d_%H%M%S").sql.gz"
    
    # Créer le backup
    if pg_dump \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --format=plain \
        --no-owner \
        --no-acl \
        2>> "$LOG_FILE" | gzip > "$safety_backup"; then
        
        log "Backup de sécurité créé: $safety_backup"
    else
        log "WARNING: Impossible de créer le backup de sécurité"
    fi
    
    unset PGPASSWORD
}

drop_and_recreate_database() {
    log "Suppression et recréation de la base de données..."
    
    export PGPASSWORD="$POSTGRES_PASSWORD"
    
    # Se connecter à la base postgres pour drop/create
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres <<EOF
-- Terminer toutes les connexions actives
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '$POSTGRES_DB'
  AND pid <> pg_backend_pid();

-- Supprimer la base
DROP DATABASE IF EXISTS $POSTGRES_DB;

-- Recréer la base
CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER;
EOF
    
    unset PGPASSWORD
    
    log "Base de données recréée"
}

restore_backup() {
    local backup_file=$1
    
    log "Restauration du backup: $backup_file"
    
    export PGPASSWORD="$POSTGRES_PASSWORD"
    
    # Décompresser et restaurer
    if gunzip -c "$backup_file" | psql \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        2>> "$LOG_FILE"; then
        
        log "Restauration terminée avec succès"
    else
        error "Échec de la restauration"
    fi
    
    unset PGPASSWORD
}

verify_restore() {
    log "Vérification de la restauration..."
    
    export PGPASSWORD="$POSTGRES_PASSWORD"
    
    # Compter les tables
    table_count=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
    
    # Compter les enregistrements dans la table users (exemple)
    user_count=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "0")
    
    unset PGPASSWORD
    
    log "Tables restaurées: $table_count"
    log "Utilisateurs: $user_count"
    
    if [ "$table_count" -lt 1 ]; then
        error "Aucune table restaurée - la restauration a échoué"
    fi
}

confirm_restore() {
    local backup_file=$1
    
    echo ""
    echo "========================================="
    echo "ATTENTION: RESTAURATION DE BASE DE DONNÉES"
    echo "========================================="
    echo "Base de données: $POSTGRES_DB"
    echo "Fichier de backup: $backup_file"
    echo ""
    echo "Cette opération va:"
    echo "  1. Créer un backup de sécurité"
    echo "  2. SUPPRIMER toutes les données actuelles"
    echo "  3. Restaurer les données du backup"
    echo ""
    read -p "Êtes-vous sûr de vouloir continuer? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log "Restauration annulée par l'utilisateur"
        exit 0
    fi
}

# ===================================
# MAIN
# ===================================

main() {
    log "========================================="
    log "Démarrage de la restauration PostgreSQL"
    log "========================================="
    
    # Vérifier les arguments
    if [ $# -eq 0 ]; then
        usage
    fi
    
    # Déterminer le fichier de backup
    if [ "$1" == "latest" ]; then
        BACKUP_FILE=$(find_latest_backup)
        log "Backup le plus récent: $BACKUP_FILE"
    else
        BACKUP_FILE=$1
    fi
    
    # Exécution des étapes
    check_prerequisites
    verify_backup_file "$BACKUP_FILE"
    confirm_restore "$BACKUP_FILE"
    create_backup_before_restore
    drop_and_recreate_database
    restore_backup "$BACKUP_FILE"
    verify_restore
    
    log "========================================="
    log "Restauration terminée avec succès"
    log "========================================="
}

# Exécuter le script
main "$@"
