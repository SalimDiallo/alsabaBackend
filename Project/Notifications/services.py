import structlog
from .models import Notification, Device
from .tasks import send_push_notification_task, send_email_notification_task

logger = structlog.get_logger(__name__)

class NotificationService:
    """
    Service unifié pour envoyer des notifications via plusieurs canaux (In-App, Push, Email).
    Utilise Celery pour l'envoi asynchrone (sauf pour la création DB qui est rapide).
    """

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
            channels (list): Liste des canaux ['db', 'push', 'email']. Défaut: tous.
        """
        if channels is None:
            channels = ['db', 'push'] # Par défaut pas d'email pour éviter le spam, à activer explicitement

        if data is None:
            data = {}

        # 1. Enregistrement en base de données (In-App History)
        # On le fait de manière synchrone pour immédiateté dans l'UI si l'user refresh
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

        # 2. Push Notification (FCM) - Async
        if 'push' in channels:
            # On récupère tous les tokens actifs de l'utilisateur
            device_tokens = list(Device.objects.filter(user=user, is_active=True).values_list('fcm_token', flat=True))
            
            if device_tokens:
                # Appel Tâche Celery
                send_push_notification_task.delay(
                    registration_ids=device_tokens,
                    title=title,
                    body=body,
                    data=data
                )
            else:
                logger.debug("no_active_devices_for_push", user_id=str(user.id))

        # 3. Email - Async
        if 'email' in channels and user.email:
             # Appel Tâche Celery
             send_email_notification_task.delay(
                 email=user.email,
                 subject=title,
                 message=body # Ou utiliser un template HTML dédié dans la tâche
             )
