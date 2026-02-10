#!/usr/bin/env python3
"""
Script de monitoring des backups PostgreSQL
Vérifie l'état des backups et envoie des alertes si nécessaire
"""
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import structlog

# Configuration du logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

# Configuration
BACKUP_DIR = Path(os.getenv('BACKUP_DIR', '/backups'))
BACKUP_RETENTION_DAYS = int(os.getenv('BACKUP_RETENTION_DAYS', 30))
SENTRY_DSN = os.getenv('SENTRY_DSN')
ALERT_WEBHOOK_URL = os.getenv('ALERT_WEBHOOK_URL')  # Slack, Discord, etc.


def check_last_backup():
    """Vérifie le dernier backup effectué"""
    metrics_file = BACKUP_DIR / 'last_backup.json'
    
    if not metrics_file.exists():
        logger.error("no_backup_metrics", message="Aucun fichier de métriques trouvé")
        return {
            'status': 'error',
            'message': 'Aucun backup trouvé',
            'severity': 'critical'
        }
    
    try:
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
        
        # Vérifier le statut
        if metrics.get('status') != 'success':
            logger.error(
                "backup_failed",
                status=metrics.get('status'),
                error=metrics.get('error')
            )
            return {
                'status': 'error',
                'message': f"Dernier backup échoué: {metrics.get('error')}",
                'severity': 'critical'
            }
        
        # Vérifier l'âge du backup
        backup_time = datetime.fromisoformat(metrics['timestamp'].replace('Z', '+00:00'))
        age_hours = (datetime.now(backup_time.tzinfo) - backup_time).total_seconds() / 3600
        
        if age_hours > 25:  # Plus de 25 heures (backup quotidien manqué)
            logger.warning(
                "backup_outdated",
                age_hours=age_hours,
                last_backup=metrics['timestamp']
            )
            return {
                'status': 'warning',
                'message': f"Dernier backup trop ancien: {age_hours:.1f}h",
                'severity': 'warning'
            }
        
        # Vérifier la taille du backup
        size_mb = metrics.get('size_bytes', 0) / (1024 * 1024)
        if size_mb < 1:  # Moins de 1MB
            logger.warning(
                "backup_too_small",
                size_mb=size_mb,
                backup_file=metrics.get('backup_file')
            )
            return {
                'status': 'warning',
                'message': f"Backup suspicieusement petit: {size_mb:.2f}MB",
                'severity': 'warning'
            }
        
        logger.info(
            "backup_healthy",
            age_hours=age_hours,
            size_mb=size_mb,
            backup_file=metrics.get('backup_file')
        )
        
        return {
            'status': 'ok',
            'message': f"Backup OK (Age: {age_hours:.1f}h, Taille: {size_mb:.1f}MB)",
            'severity': 'info'
        }
        
    except Exception as e:
        logger.error("metrics_read_error", error=str(e))
        return {
            'status': 'error',
            'message': f"Erreur lecture métriques: {str(e)}",
            'severity': 'critical'
        }


def check_disk_space():
    """Vérifie l'espace disque disponible"""
    try:
        import shutil
        stats = shutil.disk_usage(BACKUP_DIR)
        
        free_gb = stats.free / (1024 ** 3)
        percent_free = (stats.free / stats.total) * 100
        
        if percent_free < 10:
            logger.error(
                "disk_space_critical",
                free_gb=free_gb,
                percent_free=percent_free
            )
            return {
                'status': 'error',
                'message': f"Espace disque critique: {free_gb:.1f}GB ({percent_free:.1f}%)",
                'severity': 'critical'
            }
        elif percent_free < 20:
            logger.warning(
                "disk_space_low",
                free_gb=free_gb,
                percent_free=percent_free
            )
            return {
                'status': 'warning',
                'message': f"Espace disque faible: {free_gb:.1f}GB ({percent_free:.1f}%)",
                'severity': 'warning'
            }
        
        logger.info(
            "disk_space_ok",
            free_gb=free_gb,
            percent_free=percent_free
        )
        
        return {
            'status': 'ok',
            'message': f"Espace disque OK: {free_gb:.1f}GB ({percent_free:.1f}%)",
            'severity': 'info'
        }
        
    except Exception as e:
        logger.error("disk_check_error", error=str(e))
        return {
            'status': 'error',
            'message': f"Erreur vérification disque: {str(e)}",
            'severity': 'warning'
        }


def check_backup_count():
    """Vérifie le nombre de backups disponibles"""
    try:
        backups = list(BACKUP_DIR.glob('backup_*.sql.gz'))
        count = len(backups)
        
        if count == 0:
            logger.error("no_backups_found")
            return {
                'status': 'error',
                'message': "Aucun backup trouvé",
                'severity': 'critical'
            }
        elif count < 3:
            logger.warning("few_backups", count=count)
            return {
                'status': 'warning',
                'message': f"Peu de backups disponibles: {count}",
                'severity': 'warning'
            }
        
        logger.info("backup_count_ok", count=count)
        return {
            'status': 'ok',
            'message': f"{count} backups disponibles",
            'severity': 'info'
        }
        
    except Exception as e:
        logger.error("backup_count_error", error=str(e))
        return {
            'status': 'error',
            'message': f"Erreur comptage backups: {str(e)}",
            'severity': 'warning'
        }


def send_alert(checks):
    """Envoie une alerte si nécessaire"""
    # Filtrer les checks avec problèmes
    issues = [c for c in checks if c['status'] != 'ok']
    
    if not issues:
        return
    
    # Déterminer la sévérité maximale
    severity_order = {'info': 0, 'warning': 1, 'critical': 2}
    max_severity = max(issues, key=lambda x: severity_order.get(x['severity'], 0))['severity']
    
    # Construire le message
    message = f"🚨 Alerte Backup PostgreSQL ({max_severity.upper()})\n\n"
    for issue in issues:
        emoji = "❌" if issue['severity'] == 'critical' else "⚠️"
        message += f"{emoji} {issue['message']}\n"
    
    logger.warning("backup_alert", severity=max_severity, issues=len(issues))
    
    # Envoyer via webhook si configuré
    if ALERT_WEBHOOK_URL:
        try:
            import requests
            payload = {
                'text': message,
                'severity': max_severity,
                'timestamp': datetime.utcnow().isoformat()
            }
            response = requests.post(ALERT_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("alert_sent", webhook=ALERT_WEBHOOK_URL)
        except Exception as e:
            logger.error("alert_send_failed", error=str(e))
    
    # Envoyer à Sentry si configuré
    if SENTRY_DSN and max_severity == 'critical':
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=SENTRY_DSN)
            sentry_sdk.capture_message(
                message,
                level='error' if max_severity == 'critical' else 'warning'
            )
            logger.info("sentry_alert_sent")
        except Exception as e:
            logger.error("sentry_alert_failed", error=str(e))


def main():
    """Point d'entrée principal"""
    logger.info("backup_monitor_started")
    
    # Effectuer les vérifications
    checks = [
        check_last_backup(),
        check_disk_space(),
        check_backup_count(),
    ]
    
    # Envoyer des alertes si nécessaire
    send_alert(checks)
    
    # Résumé
    ok_count = sum(1 for c in checks if c['status'] == 'ok')
    logger.info(
        "backup_monitor_completed",
        total_checks=len(checks),
        ok_count=ok_count,
        issues=len(checks) - ok_count
    )


if __name__ == '__main__':
    main()
