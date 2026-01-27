import structlog
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal
from ..models import Wallet, Transaction, PaymentMethod
from .flutterwave_service import flutterwave_service
from .payment_method_service import payment_method_service

logger = structlog.get_logger(__name__)


class WalletService:
    """
    Service de gestion des portefeuilles et transactions
    """

    @staticmethod
    def create_wallet_for_user(user):
        """
        Crée un wallet pour un nouvel utilisateur

        Args:
            user: Instance User

        Returns:
            Wallet: Le wallet créé
        """
        wallet = Wallet.objects.create(user=user)
        logger.info("wallet_created", user_id=str(user.id), wallet_id=str(wallet.id))
        return wallet

    @staticmethod
    def get_or_create_wallet(user):
        """
        Récupère ou crée le wallet d'un utilisateur

        Args:
            user: Instance User

        Returns:
            Wallet: Le wallet de l'utilisateur
        """
        wallet, created = Wallet.objects.get_or_create(user=user)
        if created:
            logger.info("wallet_auto_created", user_id=str(user.id), wallet_id=str(wallet.id))
        return wallet

    @staticmethod
    def initiate_deposit(user, amount, payment_method, card_details=None, request_meta=None,
                        payment_method_id=None, save_payment_method=False, 
                        payment_method_label=None, redirect_url=None):
        """
        Initie un dépôt sur le wallet

        Args:
            user: Instance User
            amount: Montant dans la devise du wallet
            payment_method: 'card' ou 'orange_money'
            card_details: Détails de la carte (requis si pas de payment_method_id)
            request_meta: Métadonnées de la requête
            payment_method_id: ID d'une méthode de paiement sauvegardée (optionnel)
            save_payment_method: Sauvegarder cette méthode pour usage futur
            payment_method_label: Nom pour la méthode sauvegardée

        Returns:
            dict: Résultat avec transaction et payment_link
        """
        # Vérification KYC
        if user.kyc_status != 'verified':
            return {
                "success": False,
                "error": "Vérification d'identité requise avant les dépôts",
                "code": "kyc_required"
            }

        # Récupération du wallet
        wallet = WalletService.get_or_create_wallet(user)

        # Utiliser Decimal pour la précision
        amount_dec = Decimal(str(amount))

        # Validation du montant selon la devise
        if not WalletService._validate_amount_for_currency(amount_dec, wallet.currency):
            return {
                "success": False,
                "error": f"Montant invalide pour la devise {wallet.currency}",
                "code": "invalid_amount"
            }

        # Calcul des frais selon la devise
        fee_amount = WalletService._calculate_deposit_fee(amount_dec, payment_method, wallet.currency)

        # Gestion de la méthode de paiement sauvegardée
        saved_payment_method = None
        if payment_method_id:
            try:
                method_type = 'card' if payment_method == 'card' else 'orange_money'
                saved_payment_method = payment_method_service.get_payment_method(
                    user, payment_method_id, method_type=method_type
                )
                # Utiliser les informations de la méthode sauvegardée
                if payment_method == 'card':
                    # NOTE: Sans implémentation de la Tokenization Flutterwave (v3/tokenized-charges),
                    # on ne peut pas encore débiter une carte juste avec un ID et un CVV.
                    # L'utilisateur doit donc fournir les détails complets à chaque fois pour l'instant.
                    # TODO: Implémenter la tokenisation après test réussi pour éviter la saisie répétée.
                    if not card_details or not card_details.get('number') or not card_details.get('cvv'):
                        return {
                            "success": False,
                            "error": "Les détails complets de la carte (numéro, expiration, CVV) sont requis pour cette transaction",
                            "code": "card_details_incomplete"
                        }
                    # saved_payment_method est gardé pour le tracking historique de l'usage.
                elif payment_method == 'orange_money':
                    # Pour Orange Money, on peut utiliser directement le numéro sauvegardé
                    # Mais on utilise déjà user.full_phone_number dans Flutterwave, donc pas de changement
                    pass
            except (PaymentMethod.DoesNotExist, ValueError) as e:
                return {
                    "success": False,
                    "error": f"Méthode de paiement non trouvée ou invalide: {str(e)}",
                    "code": "payment_method_not_found"
                }

        with db_transaction.atomic():
            # Création de la transaction
            transaction = Transaction.objects.create(
                wallet=wallet,
                transaction_type='deposit',
                payment_method=payment_method,
                payment_method_saved=saved_payment_method,
                amount_cents=int(amount_dec * 100),
                fee_cents=int(fee_amount * 100),
                currency=wallet.currency,
                user_ip=request_meta.get('ip') if request_meta else None,
                user_agent=request_meta.get('user_agent') if request_meta else None,
            )

            # Préparer l'adresse pour Flutterwave
            address_data = None
            # Mapper le code pays (ex: +33 -> FR)
            # On essaie d'abord kyc_nationality, sinon on déduit du country_code
            country_iso = user.kyc_nationality or "FR" 
            if len(country_iso) > 2: # Si c'est un nom complet, on met un défaut ou on tronque
                country_iso = "FR" # Idéalement utiliser une lib de mapping

            if user.city or user.postal_code or user.state or user.kyc_address:
                address_data = {
                    "city": user.city or "Unknown",
                    "postal_code": user.postal_code or "00000",
                    "state": user.state or "Unknown",
                    "line1": user.kyc_address or "Address not provided",
                    "country": country_iso
                }
            elif country_iso:
                # Flutterwave requiert au moins le pays pour le customer
                address_data = {"country": country_iso}

        flutterwave_result = flutterwave_service.initiate_deposit(
            amount=float(amount_dec + fee_amount),
            currency=wallet.currency,
            payment_method=payment_method,
            customer_email=user.email,
            customer_phone=user.phone_number, # Numéro national (7-10 chiffres)
            country_code=user.country_code.replace('+', ''), # Ex: 33
            customer_name=f"{user.first_name} {user.last_name}".strip() or user.full_phone_number,
            card_details=card_details,
            address=address_data,
            customer_id=user.flutterwave_customer_id,
            redirect_url=redirect_url, # Passer l'URL demandée
            meta={
                "transaction_id": str(transaction.id),
                "user_id": str(user.id),
                "internal_reference": transaction.id.hex[:16]
            }
        )
        
        # Si un ID customer a été créé ou récupéré via 409 fallback, on le cache
        flw_customer_id = flutterwave_result.get("customer_id") # Note: nécessite d'être retourné par les services
        if not user.flutterwave_customer_id and flw_customer_id:
            user.flutterwave_customer_id = flw_customer_id
            user.save(update_fields=['flutterwave_customer_id'])
        
        with db_transaction.atomic():
            # Sauvegarder la méthode de paiement si demandé
            if save_payment_method and not saved_payment_method and payment_method == 'card' and card_details:
                try:
                    new_payment_method = payment_method_service.create_card_payment_method(
                        user=user,
                        label=payment_method_label or f"Carte {card_details.get('number', '')[-4:]}",
                        card_number=card_details['number'],
                        card_expiry_month=str(card_details['exp_month']),
                        card_expiry_year=str(card_details['exp_year']),
                        card_cvv=card_details['cvv'],  # Ne sera pas stocké
                        is_default=False
                    )
                    transaction.payment_method_saved = new_payment_method
                except Exception as e:
                    logger.exception("failed_to_save_payment_method", user_id=str(user.id))

            if not flutterwave_result["success"]:
                transaction.mark_failed(
                    error_message=flutterwave_result.get("error"),
                    error_code=flutterwave_result.get("code")
                )
                return {
                    "success": False,
                    "error": flutterwave_result.get("error"),
                    "code": flutterwave_result.get("code")
                }

            # Mise à jour de la transaction avec les références Flutterwave
            transaction.flutterwave_reference = flutterwave_result["reference"]
            # Utiliser charge_id pour les dépôts (carte ou Orange Money)
            transaction.flutterwave_transaction_id = str(flutterwave_result.get("charge_id", ""))
            transaction.status = 'processing'
            transaction.save()

            logger.info(
                "deposit_initiated",
                user_id=str(user.id),
                transaction_id=str(transaction.id),
                amount=amount,
                payment_method=payment_method,
                flutterwave_ref=flutterwave_result["reference"]
            )

            return {
                "success": True,
                "transaction": transaction,
                "payment_link": flutterwave_result.get("payment_link"),  # Peut ne pas exister pour Orange Money
                "reference": flutterwave_result["reference"],
                "amount": amount,
                "fee": fee_amount,
                "total": amount + fee_amount
            }

    @staticmethod
    def initiate_withdrawal(user, amount, payment_method, account_details, request_meta=None,
                           payment_method_id=None, save_payment_method=False, payment_method_label=None):
        """
        Initie un retrait du wallet

        Args:
            user: Instance User
            amount: Montant dans la devise du wallet
            payment_method: 'card' (compte bancaire) ou 'orange_money'
            account_details: Détails du compte destinataire (requis si pas de payment_method_id)
            request_meta: Métadonnées de la requête
            payment_method_id: ID d'une méthode de paiement sauvegardée (optionnel)
            save_payment_method: Sauvegarder cette méthode pour usage futur
            payment_method_label: Nom pour la méthode sauvegardée

        Returns:
            dict: Résultat de l'opération
        """
        # Vérification KYC
        if user.kyc_status != 'verified':
            return {
                "success": False,
                "error": "Vérification d'identité requise avant les retraits",
                "code": "kyc_required"
            }

        # Utiliser Decimal pour la précision absolue
        amount_dec = Decimal(str(amount))

        with db_transaction.atomic():
            # VERROUILLAGE PHYSIQUE (Pessimistic Locking)
            wallet = Wallet.objects.select_for_update().get(user=user)

            # Validation du montant selon la devise
            if not WalletService._validate_amount_for_currency(amount_dec, wallet.currency):
                return {
                    "success": False,
                    "error": f"Montant invalide pour la devise {wallet.currency}",
                    "code": "invalid_amount"
                }

            # Calcul des frais selon la devise
            fee_amount = WalletService._calculate_withdrawal_fee(amount_dec, payment_method, wallet.currency)

            # Vérification du solde rigoureuse sous verrou
            total_deduct = amount_dec + fee_amount
            if wallet.balance_cents < int(total_deduct * 100):
                return {
                    "success": False,
                    "error": "Solde insuffisant pour couvrir les frais",
                    "code": "insufficient_balance_with_fees",
                    "available_balance": wallet.balance,
                    "required_amount": total_deduct,
                    "currency": wallet.currency
                }

            # Gestion de la méthode de paiement sauvegardée
            saved_payment_method = None
            if payment_method_id:
                try:
                    method_type = 'bank_account' if payment_method == 'card' else 'orange_money'
                    saved_payment_method = payment_method_service.get_payment_method(
                        user, payment_method_id, method_type=method_type
                    )
                    # Construire account_details à partir de la méthode sauvegardée
                    if payment_method == 'card':
                        account_details = {
                            'account_number': saved_payment_method.account_number,
                            'bank_code': saved_payment_method.bank_code,
                            'account_name': saved_payment_method.account_name,
                            'bank_country': saved_payment_method.bank_country,
                            'type': 'bank_account'
                        }
                    elif payment_method == 'orange_money':
                        account_details = {
                            'phone_number': saved_payment_method.orange_money_number,
                            'beneficiary_name': f"{user.first_name} {user.last_name}".strip() or user.full_phone_number
                        }
                except (PaymentMethod.DoesNotExist, ValueError) as e:
                    return {
                        "success": False,
                        "error": f"Méthode de paiement non trouvée ou invalide: {str(e)}",
                        "code": "payment_method_not_found"
                    }

            # Création de la transaction
            transaction = Transaction.objects.create(
                wallet=wallet,
                transaction_type='withdrawal',
                payment_method=payment_method,
                payment_method_saved=saved_payment_method,
                amount_cents=int(amount_dec * 100),
                fee_cents=int(fee_amount * 100),
                currency=wallet.currency,
                user_ip=request_meta.get('ip') if request_meta else None,
                user_agent=request_meta.get('user_agent') if request_meta else None,
                status='pending'
            )

            # PROTECTION: Débit immédiat du solde pour éviter les duplications (Race Condition)
            wallet.subtract_balance(total_deduct)
            transaction.balance_adjusted = True

            # Stockage des détails de paiement
            if payment_method == 'card':
                transaction.card_last_four = account_details.get('account_number', '')[-4:] if account_details.get('account_number') else None
            elif payment_method == 'orange_money':
                transaction.orange_money_number = account_details.get('phone_number')

            transaction.save()
            
            # Sauvegarder la méthode de paiement si demandé
            if save_payment_method and not saved_payment_method:
                try:
                    if payment_method == 'card':
                        new_payment_method = payment_method_service.create_bank_account_payment_method(
                            user=user,
                            label=payment_method_label or f"Compte {account_details.get('account_number', '')[-4:]}",
                            account_number=account_details.get('account_number'),
                            bank_code=account_details.get('bank_code'),
                            account_name=account_details.get('account_name'),
                            bank_name=account_details.get('bank_name'),
                            bank_country=account_details.get('bank_country'),
                            is_default=False
                        )
                    elif payment_method == 'orange_money':
                        new_payment_method = payment_method_service.create_orange_money_payment_method(
                            user=user,
                            label=payment_method_label or "Mon Orange Money",
                            orange_money_number=account_details.get('phone_number'),
                            is_default=False
                        )
                    transaction.payment_method_saved = new_payment_method
                    transaction.save()
                except Exception as e:
                    logger.exception("failed_to_save_payment_method", user_id=str(user.id))

        # APPEL FLUTTERWAVE (Hors verrou DB pour éviter de bloquer la ligne trop longtemps)
        # Préparer recipient_details selon le format attendu par Flutterwave
        recipient_details = None
        if payment_method == 'card':
            # Retrait vers compte bancaire
            recipient_details = {
                "account_number": account_details.get('account_number'),
                "bank_code": account_details.get('bank_code'),
                "account_name": account_details.get('account_name'),
                "type": account_details.get('type', 'bank_account')
            }
            if account_details.get('bank_country'):
                recipient_details["bank_country"] = account_details['bank_country']
        elif payment_method == 'orange_money':
            # Extraction du numéro national et du code pays séparément
            # On prend soit le msisdn complet soit orange_money_number
            full_phone = account_details.get('phone_number') or user.full_phone_number
            # On réuitilise la même logique que pour le dépôt pour plus de sécurité
            from Accounts.utils import AuthUtils
            country_code, national_phone = AuthUtils.parse_phone_number(full_phone)
            
            recipient_details = {
                "phone": national_phone,
                "name": account_details.get('beneficiary_name') or f"{user.first_name} {user.last_name}".strip(),
                "country_code": country_code.replace('+', '')
            }
        
        flutterwave_result = flutterwave_service.initiate_withdrawal(
            amount=float(amount_dec),  # Utilisation du Decimal converti
            payment_method=payment_method,
            recipient_details=recipient_details,
            narration=f"Wallet withdrawal - Transaction {transaction.id.hex[:8]}"
        )

        if not flutterwave_result["success"]:
            # RESTAURER LE SOLDE en cas d'échec immédiat
            wallet.add_balance(total_deduct)
            transaction.balance_adjusted = False
            
            transaction.mark_failed(
                error_message=flutterwave_result.get("error"),
                error_code=flutterwave_result.get("code")
            )
            return {
                "success": False,
                "error": flutterwave_result.get("error"),
                "code": flutterwave_result.get("code")
            }

        # Mise à jour de la transaction
        transaction.flutterwave_reference = flutterwave_result["reference"]
        # Utiliser charge_id pour les dépôts (carte ou Orange Money)
        transaction.flutterwave_transaction_id = str(flutterwave_result.get("charge_id", ""))
        transaction.status = 'processing'
        transaction.save()


        logger.info(
            "withdrawal_initiated",
            user_id=str(user.id),
            transaction_id=str(transaction.id),
            amount=amount,
            payment_method=payment_method,
            flutterwave_ref=flutterwave_result["reference"]
        )

        return {
                "success": True,
                "transaction": transaction,
                "reference": flutterwave_result["reference"],
                "amount": amount,
                "fee": fee_amount,
                "total_deducted": total_deduct
            }

    @staticmethod
    def process_webhook(flutterwave_data):
        """
        Traite un webhook Flutterwave

        Args:
            flutterwave_data: Données du webhook

        Returns:
            dict: Résultat du traitement
        """
        event_type = flutterwave_data.get("event")
        data = flutterwave_data.get("data", {})

        if event_type == "charge.completed":
            return WalletService._process_payment_webhook(data)
        elif event_type == "transfer.completed":
            return WalletService._process_transfer_webhook(data)
        else:
            logger.info("webhook_ignored", event_type=event_type)
            return {"success": True, "message": "Event ignoré"}

    @staticmethod
    def _process_payment_webhook(data):
        """Traite un webhook de paiement (dépôt)"""
        tx_ref = data.get("tx_ref")
        status = data.get("status")
        flutterwave_id = str(data.get("id"))

        try:
            transaction = Transaction.objects.get(
                flutterwave_reference=tx_ref,
                transaction_type='deposit'
            )

            if status == "successful":
                transaction.mark_completed()
                logger.info(
                    "deposit_completed_via_webhook",
                    transaction_id=str(transaction.id),
                    flutterwave_id=flutterwave_id
                )
                return {"success": True, "message": "Dépôt traité avec succès"}
            else:
                transaction.mark_failed(
                    error_message=f"Payment {status}",
                    error_code="payment_failed"
                )
                return {"success": True, "message": "Échec du dépôt enregistré"}

        except Transaction.DoesNotExist:
            logger.warning("webhook_transaction_not_found", tx_ref=tx_ref)
            return {"success": False, "error": "Transaction non trouvée"}

    @staticmethod
    def _process_transfer_webhook(data):
        """Traite un webhook de transfert (retrait)"""
        reference = data.get("reference")
        status = data.get("status")

        try:
            transaction = Transaction.objects.get(
                flutterwave_reference=reference,
                transaction_type='withdrawal'
            )

            if status == "successful":
                transaction.mark_completed()
                logger.info(
                    "withdrawal_completed_via_webhook",
                    transaction_id=str(transaction.id),
                    reference=reference
                )
                return {"success": True, "message": "Retrait traité avec succès"}
            else:
                # REMBOURSER LE SOLDE en cas d'échec du transfert
                if transaction.balance_adjusted:
                    total_to_refund = (Decimal(transaction.amount_cents) + Decimal(transaction.fee_cents)) / 100
                    transaction.wallet.add_balance(total_to_refund)
                    transaction.balance_adjusted = False
                
                transaction.mark_failed(
                    error_message=f"Transfer {status}",
                    error_code="transfer_failed"
                )
                return {"success": True, "message": "Échec du retrait enregistré et solde remboursé"}

        except Transaction.DoesNotExist:
            logger.warning("webhook_transfer_not_found", reference=reference)
            return {"success": False, "error": "Transaction non trouvée"}

    @staticmethod
    def _validate_amount_for_currency(amount, currency):
        """
        Valide le montant selon les règles de la devise

        Args:
            amount: Montant à valider
            currency: Code devise

        Returns:
            bool: True si valide
        """
        if amount <= 0:
            return False

        # Règles spécifiques selon la devise
        if currency == 'EUR':
            return amount <= 10000  # Max 10,000€
        elif currency in ['XAF', 'XOF']:  # Franc CFA
            return amount <= 5000000  # Max 5M FCFA
        elif currency == 'NGN':
            return amount <= 5000000  # Max 5M NGN
        elif currency in ['GHS', 'KES', 'ZAR']:
            return amount <= 100000  # Max 100k dans ces devises
        else:
            return amount <= 10000  # Défaut

    @staticmethod
    def _calculate_deposit_fee(amount, payment_method, currency):
        """
        Calcule les frais de dépôt selon la méthode et la devise

        Args:
            amount: Montant du dépôt
            payment_method: 'card' ou 'orange_money'
            currency: Code devise

        Returns:
            Decimal: Montant des frais
        """
        if payment_method == 'card':
            # Frais pour carte : 2.9% + frais fixes selon devise
            fee_rate = Decimal('0.029')
            if currency == 'EUR':
                fixed_fee = Decimal('0.25')
            elif currency in ['XAF', 'XOF']:
                fixed_fee = Decimal('200')  # 200 FCFA
            elif currency == 'NGN':
                fixed_fee = Decimal('100')  # 100 NGN
            else:
                fixed_fee = Decimal('1')  # 1 unité par défaut
        else:  # orange_money
            # Frais pour mobile money : 5%
            fee_rate = Decimal('0.05')
            fixed_fee = Decimal('0')

        return (amount * fee_rate) + fixed_fee

    @staticmethod
    def _calculate_withdrawal_fee(amount, payment_method, currency):
        """
        Calcule les frais de retrait selon la méthode et la devise

        Args:
            amount: Montant du retrait
            payment_method: 'card' ou 'orange_money'
            currency: Code devise

        Returns:
            Decimal: Montant des frais
        """
        if payment_method == 'card':
            # Frais pour carte : 3% + frais fixes
            fee_rate = Decimal('0.03')
            if currency == 'EUR':
                fixed_fee = Decimal('0.50')
            elif currency in ['XAF', 'XOF']:
                fixed_fee = Decimal('300')  # 300 FCFA
            elif currency == 'NGN':
                fixed_fee = Decimal('200')  # 200 NGN
            else:
                fixed_fee = Decimal('2')  # 2 unités par défaut
        else:  # orange_money
            # Frais pour mobile money : 6%
            fee_rate = Decimal('0.06')
            fixed_fee = Decimal('0')

        return (amount * fee_rate) + fixed_fee

    @staticmethod
    def _get_currency_symbol(currency):
        """Retourne le symbole de la devise"""
        symbols = {
            'EUR': '€',
            'XAF': 'FCFA',
            'XOF': 'FCFA',
            'NGN': '₦',
            'GHS': '₵',
            'KES': 'KSh',
            'ZAR': 'R',
            'TZS': 'TSh',
            'UGX': 'USh',
            'RWF': 'FRw',
            'BIF': 'FBu',
            'ZMW': 'ZK',
            'ZWD': '$',
        }
        return symbols.get(currency, currency)

    @staticmethod
    def _get_currency_name(currency):
        """Retourne le nom complet de la devise"""
        names = {
            'EUR': 'Euro',
            'XAF': 'Franc CFA (CEMAC)',
            'XOF': 'Franc CFA (BCEAO)',
            'NGN': 'Naira Nigérian',
            'GHS': 'Cedi Ghanéen',
            'KES': 'Shilling Kényan',
            'ZAR': 'Rand Sud-Africain',
            'TZS': 'Shilling Tanzanien',
            'UGX': 'Shilling Ougandais',
            'RWF': 'Franc Rwandais',
            'BIF': 'Franc Burundais',
            'ZMW': 'Kwacha Zambien',
            'ZWD': 'Dollar Zimbabwéen',
        }
        return names.get(currency, currency)

    @staticmethod
    def confirm_deposit(user, transaction_id, confirmation_data=None):
        """
        Confirme un dépôt

        Args:
            user: Instance User
            transaction_id: UUID de la transaction
            confirmation_data: Données de confirmation

        Returns:
            dict: Résultat de l'opération
        """
        try:
            # Récupération du wallet
            wallet = WalletService.get_or_create_wallet(user)

            # Récupération de la transaction
            transaction = wallet.transactions.get(
                id=transaction_id,
                transaction_type='deposit'
            )

            # Vérification du statut
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Impossible de confirmer un dépôt {transaction.get_status_display()}",
                    "code": "invalid_status"
                }

            with db_transaction.atomic():
                # Calculer le montant à créditer
                amount_to_credit = Decimal(str(transaction.amount_cents)) / Decimal('100')

                # Marquer la transaction comme terminée (cela crédite automatiquement le wallet)
                transaction.mark_completed()
                transaction.completed_at = timezone.now()
                transaction.save()

                # Rafraîchir le wallet pour obtenir le solde à jour
                wallet.refresh_from_db()

                logger.info(
                    "deposit_confirmed",
                    user_id=str(user.id),
                    transaction_id=str(transaction.id),
                    amount=amount_to_credit,
                    wallet_balance=wallet.balance
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "amount_credited": amount_to_credit,
                    "wallet_balance": wallet.balance
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.error("deposit_confirmation_error", error=str(e), transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Erreur lors de la confirmation",
                "code": "confirmation_error"
            }

    @staticmethod
    def cancel_deposit(user, transaction_id, cancellation_data):
        """
        Annule un dépôt

        Args:
            user: Instance User
            transaction_id: UUID de la transaction
            cancellation_data: Données d'annulation

        Returns:
            dict: Résultat de l'opération
        """
        try:
            # Récupération du wallet
            wallet = WalletService.get_or_create_wallet(user)

            # Récupération de la transaction
            transaction = wallet.transactions.get(
                id=transaction_id,
                transaction_type='deposit'
            )

            # Vérification du statut
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Impossible d'annuler un dépôt {transaction.get_status_display()}",
                    "code": "invalid_status"
                }

            with db_transaction.atomic():
                # Annuler la transaction
                transaction.mark_cancelled(
                    reason=cancellation_data.get("reason"),
                    notes=cancellation_data.get("notes")
                )

                logger.info(
                    "deposit_cancelled",
                    user_id=str(user.id),
                    transaction_id=str(transaction.id),
                    reason=cancellation_data.get("reason")
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "refund_amount": 0  # Pas de remboursement pour les dépôts annulés
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.exception("deposit_cancellation_error", transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Erreur lors de l'annulation",
                "code": "cancellation_error"
            }

    @staticmethod
    def confirm_withdrawal(user, transaction_id, confirmation_data=None):
        """
        Confirme un retrait

        Args:
            user: Instance User
            transaction_id: UUID de la transaction
            confirmation_data: Données de confirmation

        Returns:
            dict: Résultat de l'opération
        """
        try:
            # Récupération du wallet
            wallet = WalletService.get_or_create_wallet(user)

            # Récupération de la transaction
            transaction = wallet.transactions.get(
                id=transaction_id,
                transaction_type='withdrawal'
            )

            # Vérification du statut
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Impossible de confirmer un retrait {transaction.get_status_display()}",
                    "code": "invalid_status"
                }

            # Marquer comme terminé (le débit a déjà été fait à l'initiation)
            with db_transaction.atomic():
                transaction.status = 'completed'
                transaction.completed_at = timezone.now()
                transaction.save()

                logger.info(
                    "withdrawal_confirmed",
                    user_id=str(user.id),
                    transaction_id=str(transaction.id),
                    amount=Decimal(str(transaction.amount_cents)) / Decimal('100'),
                    wallet_balance=wallet.balance
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "amount_debited": Decimal(str(transaction.amount_cents)) / Decimal('100'),
                    "wallet_balance": wallet.balance
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.exception("withdrawal_confirmation_error", transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Erreur lors de l'confirmation",
                "code": "confirmation_error"
            }

    @staticmethod
    def cancel_withdrawal(user, transaction_id, cancellation_data):
        """
        Annule un retrait et rembourse le wallet

        Args:
            user: Instance User
            transaction_id: UUID de la transaction
            cancellation_data: Données d'annulation

        Returns:
            dict: Résultat de l'opération
        """
        try:
            # Récupération du wallet
            wallet = WalletService.get_or_create_wallet(user)

            # Récupération de la transaction
            transaction = wallet.transactions.get(
                id=transaction_id,
                transaction_type='withdrawal'
            )

            # Vérification du statut
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Impossible d'annuler un retrait {transaction.get_status_display()}",
                    "code": "invalid_status"
                }

            with db_transaction.atomic():
                # Calculer le montant à rembourser (montant + frais)
                total_amount = Decimal(str(transaction.amount_cents + transaction.fee_cents)) / Decimal('100')

                # Rembourser le wallet
                wallet.add_balance(total_amount)

                # Annuler la transaction
                transaction.mark_cancelled(
                    reason=cancellation_data.get("reason"),
                    notes=cancellation_data.get("notes")
                )

                logger.info(
                    "withdrawal_cancelled",
                    user_id=str(user.id),
                    transaction_id=str(transaction.id),
                    refund_amount=total_amount,
                    wallet_balance=wallet.balance,
                    reason=cancellation_data.get("reason")
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "refund_amount": total_amount,
                    "wallet_balance": wallet.balance
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.exception("withdrawal_cancellation_error", transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Erreur lors de l'annulation",
                "code": "cancellation_error"
            }

    @staticmethod
    def check_transaction_status(transaction):
        """
        Vérifie le statut d'une transaction auprès de Flutterwave

        Args:
            transaction: Instance Transaction

        Returns:
            dict: Statut de la transaction
        """
        try:
            if not transaction.flutterwave_transaction_id:
                return {
                    "success": False,
                    "error": "Transaction Flutterwave ID manquant",
                    "code": "missing_flutterwave_id"
                }

            if transaction.transaction_type == 'deposit':
                result = flutterwave_service.verify_transaction(
                    transaction.flutterwave_transaction_id,
                    payment_method=transaction.payment_method
                )
            else:  # withdrawal
                result = flutterwave_service.verify_transfer(
                    transaction.flutterwave_transaction_id,
                    payment_method=transaction.payment_method
                )

            if result["success"]:
                # Mapper le statut Flutterwave vers notre statut
                flutterwave_status = result.get("flutterwave_status", result.get("status"))
                mapped_status = result.get("status")  # Déjà mappé par verify_transaction/verify_transfer
                
                # Mettre à jour le statut local si nécessaire
                if mapped_status == "completed" and transaction.status != "completed":
                    # Transaction réussie côté Flutterwave, on la confirme
                    if transaction.transaction_type == 'deposit':
                        WalletService.confirm_deposit(transaction.wallet.user, transaction.id)
                    else:
                        WalletService.confirm_withdrawal(transaction.wallet.user, transaction.id)
                    # Rafraîchir la transaction
                    transaction.refresh_from_db()
                elif mapped_status in ["failed", "cancelled"] and transaction.status not in ["failed", "cancelled"]:
                    transaction.mark_failed(
                        error_message=f"Flutterwave status: {flutterwave_status}",
                        error_code="flutterwave_status_update"
                    )

            return result

        except Exception as e:
            logger.error("transaction_status_check_error", 
                        error=str(e), 
                        transaction_id=str(transaction.id))
            return {
                "success": False,
                "error": "Erreur lors de la vérification du statut",
                "code": "status_check_error"
            }

    @staticmethod
    def update_transaction_status(transaction_id, new_status, update_data=None):
        """
        Met à jour le statut d'une transaction (admin)

        Args:
            transaction_id: UUID de la transaction
            new_status: Nouveau statut
            update_data: Données supplémentaires

        Returns:
            dict: Résultat de l'opération
        """
        try:
            transaction = Transaction.objects.get(id=transaction_id)
            old_status = transaction.status

            # Validation des transitions de statut
            valid_transitions = {
                'pending': ['processing', 'completed', 'failed', 'cancelled'],
                'processing': ['completed', 'failed', 'cancelled'],
                'completed': [],  # Ne peut pas changer une fois terminée
                'failed': ['pending'],  # Peut être relancée
                'cancelled': ['pending']  # Peut être relancée
            }

            if new_status not in valid_transitions.get(old_status, []):
                return {
                    "success": False,
                    "error": f"Transition de statut invalide: {old_status} -> {new_status}",
                    "code": "invalid_status_transition"
                }

            with db_transaction.atomic():
                if new_status == 'completed':
                    transaction.mark_completed()
                elif new_status == 'failed':
                    transaction.mark_failed(
                        error_message=update_data.get("error_message"),
                        error_code=update_data.get("error_code", "manual_update")
                    )
                elif new_status == 'cancelled':
                    transaction.mark_cancelled(
                        reason=update_data.get("notes", "Annulé manuellement"),
                        notes=update_data.get("notes")
                    )
                else:
                    transaction.status = new_status
                    transaction.save()

                logger.info(
                    "transaction_status_manually_updated",
                    transaction_id=str(transaction.id),
                    old_status=old_status,
                    new_status=new_status
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "old_status": old_status,
                    "new_status": new_status
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.error("transaction_status_update_error", error=str(e), transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Erreur lors de la mise à jour du statut",
                "code": "status_update_error"
            }

    @staticmethod
    def get_wallet_statistics():
        """
        Retourne les statistiques globales des wallets

        Returns:
            dict: Statistiques
        """
        try:
            total_wallets = Wallet.objects.count()
            total_balance = Wallet.objects.aggregate(
                total=Sum('balance_cents')
            )['total'] or 0
            # Convertir de centimes en unités
            total_balance = total_balance / 100 if total_balance else 0

            transactions_stats = Transaction.objects.aggregate(
                total_count=Count('id'),
                deposits_count=Count('id', filter=Q(transaction_type='deposit')),
                withdrawals_count=Count('id', filter=Q(transaction_type='withdrawal')),
                completed_count=Count('id', filter=Q(status='completed')),
                pending_count=Count('id', filter=Q(status='pending')),
                failed_count=Count('id', filter=Q(status='failed')),
                total_volume=Sum('amount_cents', filter=Q(status='completed')) or 0,
                total_fees=Sum('fee_cents', filter=Q(status='completed')) or 0
            )

            # Volume par devise
            volume_by_currency = {}
            for currency_data in Transaction.objects.filter(status='completed').values('currency').annotate(
                volume=Sum('amount_cents'),
                count=Count('id')
            ):
                currency = currency_data['currency']
                volume_by_currency[currency] = {
                    'volume': currency_data['volume'] / 100,  # Convertir en unités
                    'count': currency_data['count']
                }

            return {
                "total_wallets": total_wallets,
                "total_balance": float(total_balance),
                "transactions": {
                    "total": transactions_stats['total_count'],
                    "deposits": transactions_stats['deposits_count'],
                    "withdrawals": transactions_stats['withdrawals_count'],
                    "completed": transactions_stats['completed_count'],
                    "pending": transactions_stats['pending_count'],
                    "failed": transactions_stats['failed_count'],
                    "total_volume": transactions_stats['total_volume'] / 100,
                    "total_fees": transactions_stats['total_fees'] / 100
                },
                "volume_by_currency": volume_by_currency,
                "generated_at": timezone.now().isoformat()
            }

        except Exception as e:
            logger.error("wallet_statistics_error", error=str(e))
            return {
                "error": "Erreur lors de la génération des statistiques",
                "generated_at": timezone.now().isoformat()
            }


# Instance globale du service
wallet_service = WalletService()