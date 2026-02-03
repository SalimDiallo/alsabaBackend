import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
import structlog
from django.utils import timezone

logger = structlog.get_logger(__name__)

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    Consumer pour gérer les notifications en temps réel par utilisateur.
    Inclut un mécanisme de Heartbeat (Ping/Pong) pour la résilience.
    """
    async def connect(self):
        self.user = self.scope["user"]
        
        if self.user.is_authenticated:
            self.group_name = f"user_notifs_{self.user.id}"
            
            # Rejoindre le groupe
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            
            # Démarrer le heartbeat
            self.heartbeat_task = asyncio.create_task(self.send_heartbeat())
            self.last_pong = timezone.now()
            
            logger.info("websocket_connected", user_id=str(self.user.id), group=self.group_name)
        else:
            await self.close()
            logger.warning("websocket_connection_rejected", reason="unauthenticated")

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            
        # Arrêter le heartbeat task
        if hasattr(self, 'heartbeat_task'):
            self.heartbeat_task.cancel()
            
        logger.info("websocket_disconnected", user_id=str(self.user.id), code=close_code)

    async def receive(self, text_data):
        """Reçoit des messages du client (ex: pong)"""
        try:
            data = json.loads(text_data)
            if data.get("type") == "pong":
                self.last_pong = timezone.now()
        except Exception:
            pass

    async def send_heartbeat(self):
        """Envoie un ping toutes les 30 secondes et vérifie la réponse"""
        try:
            while True:
                await asyncio.sleep(30)
                
                # Vérifier si on a reçu un pong récemment (max 65s)
                if (timezone.now() - self.last_pong).total_seconds() > 65:
                    logger.warning("websocket_timeout", user_id=str(self.user.id))
                    await self.close()
                    break
                
                # Envoyer le ping
                await self.send(text_data=json.dumps({"type": "ping"}))
        except asyncio.CancelledError:
            pass

    async def send_notification(self, event):
        message = event["message"]
        await self.send(text_data=json.dumps(message))
