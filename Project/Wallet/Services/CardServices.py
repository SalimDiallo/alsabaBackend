from decimal import Decimal
import structlog
from ..models import Wallet

logger = structlog.get_logger(__name__)

class DepositService:
    """
    Service pour gérer les dépôts.
    - Utilise placeholders (mocks) pour Orange Money et Carte.
    - Facile à remplacer par APIs réelles (ex: Stripe.create_charge() pour card).
    """
    @staticmethod
    def process_deposit(wallet: Wallet, amount: Decimal, method: str, reference: str = "") -> dict:
        """
        Placeholder pour dépôt.
        - Simule une validation externe.
        - Crédite le wallet si succès.
        - Retourne un dict pour la vue (success, message, details).
        """
        if method == 'orange_money':
            # Placeholder Orange Money: simule appel API (ex: https://api.orange.com/orange-money)
            # Remplacer par : requests.post('https://api.orange.com/orange-money/...', data={...})
            logger.info("placeholder_orange_money_deposit", amount=str(amount), reference=reference)
            # Simulation succès (en prod: vérifier réponse API)
            success = True
            message = "Dépôt Orange Money simulé avec succès."
        
        elif method == 'card':
            # Placeholder Carte: simule Stripe ou similaire
            # Remplacer par : stripe.Charge.create(amount=amount*100, currency=wallet.currency.code, ...)
            logger.info("placeholder_card_deposit", amount=str(amount), reference=reference)
            # Simulation succès
            success = True
            message = "Dépôt par carte simulé avec succès."
        
        else:
            raise ValueError("Méthode de dépôt invalide.")

        if success:
            wallet.deposit(amount, method, reference)
            return {'success': True, 'message': message, 'new_balance': wallet.balance}
        else:
            return {'success': False, 'message': "Échec du dépôt (simulation)."}
        
        
class WithdrawalService:
    """
    Service pour les retraits (simulation pour l'instant).
    """
    @staticmethod
    def process_withdrawal(wallet: Wallet, amount: Decimal, method: str, reference: str = "") -> dict:
        """
        Placeholder pour retrait.
        - Simule une validation externe (ex: appel Orange Money payout ou Stripe refund)
        - Débite le wallet si succès
        """
        try:
            if method == 'orange_money':
                # Placeholder Orange Money payout
                logger.info("placeholder_orange_money_withdrawal", amount=str(amount))
                success = True  # ← Simulation
                message = "Retrait Orange Money simulé avec succès."

            elif method == 'card':
                # Placeholder carte (refund)
                logger.info("placeholder_card_withdrawal", amount=str(amount))
                success = True
                message = "Retrait par carte simulé avec succès."

            elif method == 'bank_transfer':
                logger.info("placeholder_bank_transfer_withdrawal", amount=str(amount))
                success = True
                message = "Virement bancaire simulé avec succès."

            else:
                raise ValueError("Méthode de retrait non supportée.")

            if success:
                wallet.withdraw(amount, method, reference)
                return {'success': True, 'message': message, 'new_balance': wallet.balance}
            else:
                return {'success': False, 'message': "Échec du retrait (simulation)."}

        except ValueError as e:
            return {'success': False, 'message': str(e)}