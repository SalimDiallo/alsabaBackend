#!/bin/bash
#
# Script de backup automatique PostgreSQL pour ALSABA
# Effectue des backups complets avec compression et rotation
#
# Usage: ./backup.sh
#

set -e  # Arrêter en cas d'erreur
set -u  # Erreur si variable non définie

# ===================================
# CONFIGURATION
# ===================================

# Variables d'environnement (définies dans docker-compose.yml)
POSTGRES_DB="${POSTGRES_DB:-alsaba_db}"
POSTGRES_USER="${POSTGRES_USER:-alsaba_user}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-alsaba_password}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# Répertoire de backup
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# Timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/backup_${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

# Logging
LOG_FILE="${BACKUP_DIR}/backup.log"

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

check_prerequisites() {
    log "Vérification des prérequis..."
    
    # Vérifier que pg_dump est disponible
    if ! command -v pg_dump &> /dev/null; then
        error "pg_dump n'est pas installé"
    fi
    
    # Vérifier que le répertoire de backup existe
    if [ ! -d "$BACKUP_DIR" ]; then
        log "Création du répertoire de backup: $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR"
    fi
    
    # Vérifier l'espace disque disponible (minimum 1GB)
    available_space=$(df -BG "$BACKUP_DIR" | tail -1 | awk '{print $4}' | sed 's/G//')
    if [ "$available_space" -lt 1 ]; then
        error "Espace disque insuffisant: ${available_space}GB disponible"
    fi
    
    log "Prérequis OK (Espace disponible: ${available_space}GB)"
}

perform_backup() {
    log "Début du backup de la base de données: $POSTGRES_DB"
    
    # Définir le mot de passe pour pg_dump
    export PGPASSWORD="$POSTGRES_PASSWORD"
    
    # Effectuer le backup avec compression
    if pg_dump \
        -h "$POSTGRES_HOST" \
        -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --format=plain \
        --no-owner \
        --no-acl \
        --verbose \
        2>> "$LOG_FILE" | gzip > "$BACKUP_FILE"; then
        
        log "Backup créé avec succès: $BACKUP_FILE"
    else
        error "Échec du backup"
    fi
    
    # Nettoyer la variable d'environnement
    unset PGPASSWORD
}

verify_backup() {
    log "Vérification de l'intégrité du backup..."
    
    # Vérifier que le fichier existe et n'est pas vide
    if [ ! -f "$BACKUP_FILE" ]; then
        error "Le fichier de backup n'existe pas: $BACKUP_FILE"
    fi
    
    # Vérifier la taille du fichier (minimum 1KB)
    file_size=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE" 2>/dev/null)
    if [ "$file_size" -lt 1024 ]; then
        error "Le fichier de backup est trop petit: ${file_size} bytes"
    fi
    
    # Vérifier que le fichier gzip est valide
    if ! gzip -t "$BACKUP_FILE" 2>> "$LOG_FILE"; then
        error "Le fichier de backup est corrompu"
    fi
    
    log "Backup vérifié (Taille: $(du -h "$BACKUP_FILE" | cut -f1))"
}

rotate_backups() {
    log "Rotation des anciens backups (rétention: ${BACKUP_RETENTION_DAYS} jours)..."
    
    # Supprimer les backups plus anciens que BACKUP_RETENTION_DAYS
    find "$BACKUP_DIR" -name "backup_*.sql.gz" -type f -mtime +${BACKUP_RETENTION_DAYS} -delete
    
    # Compter les backups restants
    backup_count=$(find "$BACKUP_DIR" -name "backup_*.sql.gz" -type f | wc -l)
    log "Backups actuels: $backup_count"
}

send_metrics() {
    log "Envoi des métriques..."
    
    # Calculer la taille du backup
    file_size=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE" 2>/dev/null)
    
    # Créer un fichier de métriques pour monitoring
    cat > "${BACKUP_DIR}/last_backup.json" <<EOF
{
    "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "database": "$POSTGRES_DB",
    "backup_file": "$BACKUP_FILE",
    "size_bytes": $file_size,
    "status": "success"
}
EOF
    
    log "Métriques enregistrées"
}

cleanup_on_error() {
    log "Nettoyage après erreur..."
    
    # Supprimer le backup partiel si présent
    if [ -f "$BACKUP_FILE" ]; then
        rm -f "$BACKUP_FILE"
        log "Backup partiel supprimé"
    fi
    
    # Créer un fichier de métriques d'échec
    cat > "${BACKUP_DIR}/last_backup.json" <<EOF
{
    "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "database": "$POSTGRES_DB",
    "status": "failed",
    "error": "Backup failed - check logs"
}
EOF
}

# ===================================
# MAIN
# ===================================

main() {
    log "========================================="
    log "Démarrage du backup PostgreSQL"
    log "========================================="
    
    # Trap pour gérer les erreurs
    trap cleanup_on_error ERR
    
    # Exécution des étapes
    check_prerequisites
    perform_backup
    verify_backup
    rotate_backups
    send_metrics
    
    log "========================================="
    log "Backup terminé avec succès"
    log "========================================="
}

# Exécuter le script
main
