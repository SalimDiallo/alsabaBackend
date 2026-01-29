import os
import sys
import django

# Setup Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Project.settings')
django.setup()

from Accounts.models import User
from Wallet.models import Wallet

def reset_wallet():
    phone = "0660620565"
    print(f"🔍 Recherche de l'utilisateur {phone}...")
    
    # Essayer plusieurs formats
    try:
        user = User.objects.get(phone_number=phone)
    except User.DoesNotExist:
        try:
            user = User.objects.get(full_phone_number=f"+212{phone[1:]}") # +212660...
        except User.DoesNotExist:
            print(f"❌ Utilisateur non trouvé !")
            return

    print(f"✅ Utilisateur trouvé : {user.full_phone_number}")
    
    if hasattr(user, 'wallet'):
        old_currency = user.wallet.currency
        print(f"⚠️  Wallet actuel trouvé : ID={user.wallet.id}, Devise={old_currency}")
        
        user.wallet.delete()
        print(f"🗑️  Wallet supprimé avec succès !")
        
        # Vérification
        user.refresh_from_db()
        if not hasattr(user, 'wallet'):
            print(f"✅ Vérifié : L'utilisateur n'a plus de wallet.")
            print(f"➡️  Le prochain dépôt créera un nouveau wallet en USD (Sandbox Mode).")
    else:
        print(f"ℹ️  L'utilisateur n'a pas de wallet.")

if __name__ == "__main__":
    reset_wallet()
