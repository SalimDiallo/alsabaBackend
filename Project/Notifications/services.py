import structlog
from django.conf import settings
from .models import Notification, Device
from django.utils import timezone
from twilio.request_validator import RequestValidator

logger = structlog.get_logger(__name__)

class NotificationService:
    """
    Service unifié pour envoyer des notifications via plusieurs canaux (In-App, SMS/Twilio).
    Utilise Celery pour l'envoi asynchrone (sauf pour la création DB qui est rapide).
    """

    @staticmethod
    def verify_twilio_signature(uri, signature, params):
        """
        Vérifie la signature d'un webhook Twilio.
        """
        auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        if not auth_token:
            logger.error("twilio_auth_token_missing")
            return False
            
        validator = RequestValidator(auth_token)
        return validator.validate(uri, params, signature)

    @staticmethod
    def send(user, title, body, notification_type='system', data=None, channels=None):
        """
        Envoie une notification à un utilisateur.
        
        Args:
            user (User): L'utilisateur destinataire.
            title (str): Titre de la notif.
            body (str): Corps du message.
            notification_type (str): Type (transaction, offer, etc.).
            data (dict): Données méta (ex: ID transaction) pour deep linking.
            channels (list): Liste des canaux ['db', 'sms']. Défaut: tous.
        """
        if channels is None:
            channels = ['db', 'sms', 'ws', 'push'] # Ajout de 'push' par défaut

        if data is None:
            data = {}

        # 1. Enregistrement en base de données (In-App History)
        if 'db' in channels:
            try:
                Notification.objects.create(
                    user=user,
                    title=title,
                    body=body,
                    notification_type=notification_type,
                    data=data
                )
            except Exception as e:
                logger.error("notification_db_create_failed", error=str(e), user_id=str(user.id))

        # 2. WebSocket Notification (Real-time)
        if 'ws' in channels:
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                
                channel_layer = get_channel_layer()
                group_name = f"user_notifs_{user.id}"
                
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        "type": "send_notification",
                        "message": {
                            "title": title,
                            "body": body,
                            "type": notification_type,
                            "data": data,
                            "timestamp": str(timezone.now())
                        }
                    }
                )
            except Exception as e:
                logger.error("notification_ws_send_failed", error=str(e), user_id=str(user.id))

        # 3. Push Notification (FCM) - Async
        if 'push' in channels:
            # Récupérer les tokens FCM actifs pour cet utilisateur
            registration_ids = list(Device.objects.filter(
                user=user, 
                is_active=True, 
                registration_id__isnull=False
            ).values_list('registration_id', flat=True))

            if registration_ids:
                from .tasks import send_push_notification_task
                send_push_notification_task.delay(
                    registration_ids=registration_ids,
                    title=title,
                    body=body,
                    data=data
                )
            else:
                logger.debug("no_fcm_tokens_for_push", user_id=str(user.id))

        # 4. SMS Notification (Twilio) - Async
        if 'sms' in channels:
            # On récupère tous les numéros de téléphone actifs de l'utilisateur
            phone_numbers = list(Device.objects.filter(user=user, is_active=True).values_list('phone_number', flat=True))
            
            if phone_numbers:
                # Appel Tâche Celery
                from .tasks import send_sms_notification_task
                send_sms_notification_task.delay(
                    phone_numbers=phone_numbers,
                    message=f"{title}\n{body}",
                    data=data
                )
            else:
                logger.debug("no_active_phone_numbers_for_sms", user_id=str(user.id))

