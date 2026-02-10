import structlog
from django.conf import settings
from .models import Notification, Device
from django.utils import timezone
from twilio.request_validator import RequestValidator

logger = structlog.get_logger(__name__)

class NotificationService:
    """
    Unified service to send notifications via multiple channels (In-App, SMS/Twilio).
    Uses Celery for asynchronous sending (except for DB creation which is fast).
    """

    @staticmethod
    def verify_twilio_signature(uri, signature, params):
        """
        Verifies the signature of a Twilio webhook.
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
        Sends a notification to a user.
        
        Args:
            user (User): The recipient user.
            title (str): Title of the notification.
            body (str): Message body.
            notification_type (str): Type (transaction, offer, etc.).
            data (dict): Meta data (e.g.: transaction ID) for deep linking.
            channels (list): List of channels ['db', 'sms']. Default: all.
        """
        if channels is None:
            channels = ['db', 'sms', 'ws', 'push'] # Adding 'push' by default

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

        # 4. SMS Notification (Twilio) - Async
        if 'sms' in channels:
            # We retrieve all active phone numbers of the user
            phone_numbers = list(Device.objects.filter(user=user, is_active=True).values_list('phone_number', flat=True))
            
            if phone_numbers:
                # Celery Task Call
                from .tasks import send_sms_notification_task
                send_sms_notification_task.delay(
                    phone_numbers=phone_numbers,
                    message=f"{title}\n{body}",
                    data=data
                )
            else:
                logger.debug("no_active_phone_numbers_for_sms", user_id=str(user.id))

