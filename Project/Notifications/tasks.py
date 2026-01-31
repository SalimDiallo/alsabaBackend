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


@shared_task
def send_sms_notification_task(phone_numbers, message, data=None):
    """
    Envoie un SMS via Twilio à une liste de numéros de téléphone.
    
    Args:
        phone_numbers (list): Liste de numéros au format E.164
        message (str): Contenu du SMS
        data (dict): Métadonnées optionnelles (pour logging)
    """
    from twilio.rest import Client
    
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_PHONE_NUMBER')
    
    if not all([account_sid, auth_token, from_number]):
        logger.error("twilio_credentials_missing", 
                    has_sid=bool(account_sid), 
                    has_token=bool(auth_token), 
                    has_number=bool(from_number))
        return "Twilio not configured"
    
    if not phone_numbers:
        return "No phone numbers provided"
    
    try:
        client = Client(account_sid, auth_token)
    except Exception as e:
        logger.exception("twilio_client_init_failed")
        return f"Twilio client error: {str(e)}"
    
    success_count = 0
    failed_numbers = []
    
    for phone_number in phone_numbers:
        try:
            sms = client.messages.create(
                body=message,
                from_=from_number,
                to=phone_number
            )
            success_count += 1
            logger.info("sms_sent_success", to=phone_number, sid=sms.sid, status=sms.status)
        except Exception as e:
            failed_numbers.append(phone_number)
            logger.error("sms_send_failed", to=phone_number, error=str(e))
    
    if failed_numbers:
        logger.info("sms_send_partial_failure", 
                    success=success_count, 
                    failure=len(failed_numbers),
                    failed_numbers_sample=failed_numbers[:5])
    else:
        logger.info("sms_send_complete", count=success_count)
    
    return f"Sent {success_count}/{len(phone_numbers)} SMS"
