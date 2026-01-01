from twilio.rest import Client
import os
# Récupère ces valeurs depuis ta console Twilio


# Initialise le client Twilio
client = Client(os.getenv('ACCOUNT_SID'), os.getenv('AUTH_TOKEN'))

# Envoie un message via WhatsApp sandbox
message = client.messages.create(
    from_='whatsapp:+14155238886',  # Numéro sandbox par défaut
    body='Bonjour monsieur , nous somme le ervice déchange',
    to='whatsapp:+212660620565'      # Ton numéro WhatsApp (avec indicatif)
)

print(f"Message envoyé ! SID : {message.sid}")