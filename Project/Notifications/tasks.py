from celery import shared_task
import structlog
from firebase_admin import messaging, credentials, initialize_app, _apps
import os

logger = structlog.get_logger(__name__)

# Initialisation Firebase unique (Lazy loading)
def _get_firebase_app():
    if not _apps:
         # ATTENTION: En prod, il faut un vrai fichier credentials.json pointé par GOOGLE_APPLICATION_CREDENTIALS
         # Pour le dev, si pas configuré, ça plantera proprement.
         cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
         if cred_path and os.path.exists(cred_path):
             cred = credentials.Certificate(cred_path)
             return initialize_app(cred)
         else:
             logger.warning("firebase_credentials_missing", message="Push notifications won't work")
             return None
    return list(_apps.values())[0]

@shared_task
def send_push_notification_task(registration_ids, title, body, data=None):
    """
    Envoie une notification Push via FCM à une liste de devices.
    """
    app = _get_firebase_app()
    if not app:
        return "Firebase not configured"

    if not registration_ids:
        return "No tokens provided"

    # Conversion data en string pour FCM (format requis: {'key': 'str_value'})
    fcm_data = {k: str(v) for k, v in data.items()} if data else {}

    # Création du message Multicast
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=fcm_data,
        tokens=registration_ids,
    )

    try:
        response = messaging.send_each_for_multicast(message)
        
        # Gestion des tokens invalides (cleanup)
        if response.failure_count > 0:
            responses = response.responses
            failed_tokens = []
            for idx, resp in enumerate(responses):
                if not resp.success:
                    # Si le token est invalide, on pourrait le supprimer de la DB
                    # (Pour simplifier on log juste ici, mais bonne pratique de clean)
                    failed_tokens.append(registration_ids[idx])
            
            logger.info("fcm_send_partial_failure", 
                        success=response.success_count, 
                        failure=response.failure_count,
                        failed_tokens_sample=failed_tokens[:5])
        else:
             logger.info("fcm_send_success", count=response.success_count)
             
        return f"Sent {response.success_count} messages"

    except Exception as e:
        logger.exception("fcm_send_error_critical")
        return str(e)


@shared_task
def send_email_notification_task(email, subject, message):
    """
    Envoie un email simple.
    """
    from django.core.mail import send_mail
    from django.conf import settings
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@alsaba.com'),
            recipient_list=[email],
            fail_silently=False,
        )
        logger.info("email_sent_success", recipient=email, subject=subject)
        return "Email sent"
    except Exception as e:
        logger.exception("email_send_failed", recipient=email)
        return str(e)
