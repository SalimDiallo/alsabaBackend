# find_my_number.py
from twilio.rest import Client
ACCOUNT_SID = ''
AUTH_TOKEN = ''
token = ""

client = Client("", token)

# Liste tes numéros Twilio
numbers = client.incoming_phone_numbers.list()

if numbers:
    print("📞 Tes numéros Twilio :")
    for n in numbers:
        print(f"→ {n.phone_number}")
else:
    print("❌ Tu n'as pas de numéro Twilio !")
    print("   Achètes-en un dans Twilio Console")