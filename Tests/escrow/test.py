# Testez juste la RÉCUPÉRATION d'abord
transaction_id = "5580063"
from config import ESCROW_EMAIL, ESCROW_PASSWORD        
# Utilisez ce mini-script :
import requests
from base64 import b64encode

email = ESCROW_EMAIL
password = ESCROW_PASSWORD

auth = b64encode(f"{email}:{password}".encode()).decode()
headers = {"Authorization": f"Basic {auth}"}

url = f"https://api.escrow-sandbox.com/2017-09-01/transaction/{transaction_id}"
response = requests.get(url, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.text[:500]}")