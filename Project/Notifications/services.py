import structlog
from .models import Notification, Device
from django.utils import timezone

logger = structlog.get_logger(__name__)

class NotificationService:
    """
    Unified service to send notifications via multiple channels
    (In-App, WebSocket, Push FCM).
    Uses Celery for asynchronous sending (except for DB creation which is fast).

    Note: l'envoi de SMS a été retiré. L'OTP — le seul SMS du parcours — est
    envoyé par Didit (Accounts/Services/OTP_services.py), pas depuis ici.
    """

    @staticmethod
    def send(user, title, body, notification_type='system', data=None, channels=None):
        """
        Sends a notification to a user.
        
        Args:
            user (User): The recipient user.
            title (str): Title of the notification.
            body (str): Message body.
            notification_type (str): Type (transaction, offer, etc.).
            data (dict): Meta data (e.g.: transaction ID) for deep linking.
            channels (list): List of channels ['db', 'ws', 'push']. Default: all.
        """
        if channels is None:
            channels = ['db', 'ws', 'push']

        if data is None:
            data = {}

        # 1. Database recording (In-App History)
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
            # Retrieve active FCM tokens for this user
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

        # 4. Email - Async
        if 'email' in channels:
            # L'email est facultatif sur User (l'inscription se fait par
            # telephone) : la plupart des comptes n'en ont pas. On degrade en
            # silence plutot que d'echouer, les autres canaux ont deja porte
            # l'information.
            recipient = (user.email or '').strip()
            if recipient:
                from .tasks import send_email_notification_task
                send_email_notification_task.delay(
                    recipient=recipient,
                    subject=title,
                    body=body,
                )
            else:
                logger.debug("no_email_for_user", user_id=str(user.id))

        # Garde-fou : un canal inconnu passait jusqu'ici en silence (c'est ce qui
        # a fait disparaitre les notifications 'email' pendant longtemps).
        unknown = set(channels) - {'db', 'ws', 'push', 'email'}
        if unknown:
            logger.warning(
                "notification_unknown_channels_ignored",
                channels=sorted(unknown),
                user_id=str(user.id),
            )

