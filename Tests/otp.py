from twilio.rest import Client

# Récupère ces valeurs depuis ta console Twilio
ACCOUNT_SID = ''
AUTH_TOKEN = ''

# Initialise le client Twilio
client = Client(ACCOUNT_SID, AUTH_TOKEN)

# Envoie un message via WhatsApp sandbox
message = client.messages.create(
    from_='whatsapp:+14155238886',  # Numéro sandbox par défaut
    body='Bonjour monsieur , nous somme le ervice déchange',
    to='whatsapp:+212660620565'      # Ton numéro WhatsApp (avec indicatif)
)

print(f"Message envoyé ! SID : {message.sid}")