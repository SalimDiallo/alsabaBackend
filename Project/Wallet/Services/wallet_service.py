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
    Service for managing wallets and transactions.
    """

    @staticmethod
    def create_wallet_for_user(user):
        """
        Creates a wallet for a new user.

        Args:
            user: User instance

        Returns:
            Wallet: The created wallet
        """
        wallet = Wallet.objects.create(user=user)
        logger.info("wallet_created", user_id=str(user.id), wallet_id=str(wallet.id))
        return wallet

    @staticmethod
    def get_or_create_wallet(user):
        """
        Retrieves or creates a user's wallet.

        Args:
            user: User instance

        Returns:
            Wallet: The user's wallet
        """
        wallet, created = Wallet.objects.get_or_create(user=user)
        if created:
            logger.info("wallet_auto_created", user_id=str(user.id), wallet_id=str(wallet.id))
        return wallet

    @staticmethod
    def initiate_deposit(user, amount, payment_method, card_details=None, request_meta=None,
                        payment_method_id=None, save_payment_method=False, 
                        payment_method_label=None, redirect_url=None, card_token=None):
        """
        Initiates a deposit to the wallet.
        
        Args:
            user: User instance
            amount: Amount in wallet currency
            payment_method: 'card' or 'orange_money'
            card_details: Card details (required if no payment_method_id or card_token)
            request_meta: Request metadata
            payment_method_id: ID of a saved payment method (optional)
            save_payment_method: Save this method for future use
            payment_method_label: Name for the saved method
            card_token: Card token (for PCI-DSS compliant frontend)
            
        Returns:
            dict: Result with transaction and payment_link
        """
        # KYC Verification
        if user.kyc_status != 'verified':
            return {
                "success": False,
                "error": "Identity verification required before deposits",
                "code": "kyc_required"
            }

        # Retrieve wallet
        wallet = WalletService.get_or_create_wallet(user)

        # Use Decimal for precision
        amount_dec = Decimal(str(amount))

        # Amount validation per currency
        if not WalletService._validate_amount_for_currency(amount_dec, wallet.currency):
            return {
                "success": False,
                "error": f"Invalid amount for currency {wallet.currency}",
                "code": "invalid_amount"
            }

        # Calculate fees based on currency
        fee_amount = WalletService._calculate_deposit_fee(amount_dec, payment_method, wallet.currency)

        # Handle saved payment method
        saved_payment_method = None
        if payment_method_id:
            try:
                method_type = 'card' if payment_method == 'card' else 'orange_money'
                saved_payment_method = payment_method_service.get_payment_method(
                    user, payment_method_id, method_type=method_type
                )
                if payment_method == 'card':
                    # TODO: Link the saved_payment_method.flutterwave_token
                    # For now keep existing logic requesting details if no full tokenization
                    if not card_details and not card_token:
                         # If we have a payment_method_id, we should be able to deduce a token or customer_id
                         pass 
            except (PaymentMethod.DoesNotExist, ValueError) as e:
                return {
                    "success": False,
                    "error": f"Payment method not found or invalid: {str(e)}",
                    "code": "payment_method_not_found"
                }

        with db_transaction.atomic():
            # Transaction creation
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

            # Prepare address for Flutterwave
            address_data = None
            country_iso = user.kyc_nationality or "FR" 
            if len(country_iso) > 2:
                country_iso = "FR"

            if user.city or user.postal_code or user.state or user.kyc_address:
                address_data = {
                    "city": user.city or "Unknown",
                    "postal_code": user.postal_code or "00000",
                    "state": user.state or "Unknown",
                    "line1": user.kyc_address or "Address not provided",
                    "country": country_iso
                }
            elif country_iso:
                address_data = {"country": country_iso}

        flutterwave_result = flutterwave_service.initiate_deposit(
            amount=float(amount_dec + fee_amount),
            currency=wallet.currency,
            payment_method=payment_method,
            customer_email=user.email,
            customer_phone=user.phone_number, # National number (7-10 digits)
            country_code=user.country_code.replace('+', ''), # Ex: 33
            customer_name=(f"{user.first_name} {user.last_name}".strip() or 
                           f"User {user.full_phone_number}"),
            card_details=card_details,
            card_token=card_token,
            address=address_data,
            customer_id=user.flutterwave_customer_id,
            redirect_url=redirect_url, # Pass requested URL
            meta={
                "transaction_id": str(transaction.id),
                "user_id": str(user.id),
                "internal_reference": transaction.id.hex[:16]
            }
        )
        
        # If a customer ID was created or retrieved via 409 fallback, cache it
        flw_customer_id = flutterwave_result.get("customer_id") # Note: needs to be returned by services
        if not user.flutterwave_customer_id and flw_customer_id:
            user.flutterwave_customer_id = flw_customer_id
            user.save(update_fields=['flutterwave_customer_id'])
        
        with db_transaction.atomic():
            # Save payment method if requested
            if save_payment_method and not saved_payment_method and payment_method == 'card' and card_details:
                try:
                    new_payment_method = payment_method_service.create_card_payment_method(
                        user=user,
                        label=payment_method_label or f"Card {card_details.get('number', '')[-4:]}",
                        card_number=card_details['number'],
                        card_expiry_month=str(card_details['exp_month']),
                        card_expiry_year=str(card_details['exp_year']),
                        card_cvv=card_details['cvv'],  # Will not be stored
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

            # Update transaction with Flutterwave references
            transaction.flutterwave_reference = flutterwave_result["reference"]
            # Use charge_id for deposits (card or Orange Money)
            transaction.flutterwave_transaction_id = str(flutterwave_result.get("charge_id", ""))
            
            # Use status returned by Flutterwave if consistent
            flw_status = flutterwave_result.get("status")
            if flw_status == "requires_authorization":
                transaction.status = 'pending' # Waiting for user action
            elif flw_status == "successful":
                transaction.status = 'processing' # Will be finalized by webhook
            else:
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
                "payment_link": flutterwave_result.get("payment_link"),  # May not exist for Orange Money
                "reference": flutterwave_result["reference"],
                "amount": amount,
                "fee": fee_amount,
                "total": amount + fee_amount,
                "currency": wallet.currency
            }

    @staticmethod
    def initiate_withdrawal(user, amount, payment_method, account_details, request_meta=None,
                           payment_method_id=None, save_payment_method=False, payment_method_label=None):
        """
        Initiates a withdrawal from the wallet.

        Args:
            user: User instance
            amount: Amount in wallet currency
            payment_method: 'card' (bank account) or 'orange_money'
            account_details: Recipient account details (required if no payment_method_id)
            request_meta: Request metadata
            payment_method_id: ID of a saved payment method (optional)
            save_payment_method: Save this method for future use
            payment_method_label: Name for the saved method

        Returns:
            dict: Result of the operation
        """
        # KYC Verification
        if user.kyc_status != 'verified':
            return {
                "success": False,
                "error": "Identity verification required before withdrawals",
                "code": "kyc_required"
            }

        # Use Decimal for absolute precision
        amount_dec = Decimal(str(amount))

        with db_transaction.atomic():
            # PHYSICAL LOCKING (Pessimistic Locking)
            wallet = Wallet.objects.select_for_update().get(user=user)

            # Amount validation per currency
            if not WalletService._validate_amount_for_currency(amount_dec, wallet.currency):
                return {
                    "success": False,
                    "error": f"Invalid amount for currency {wallet.currency}",
                    "code": "invalid_amount"
                }

            # Calculate fees based on currency
            fee_amount = WalletService._calculate_withdrawal_fee(amount_dec, payment_method, wallet.currency)

            # Rigorous balance check under lock
            total_deduct = amount_dec + fee_amount
            if wallet.balance_cents < int(total_deduct * 100):
                return {
                    "success": False,
                    "error": "Insufficient balance to cover fees",
                    "code": "insufficient_balance_with_fees",
                    "available_balance": wallet.balance,
                    "required_amount": total_deduct,
                    "currency": wallet.currency
                }

            # Handle saved payment method
            saved_payment_method = None
            if payment_method_id:
                try:
                    method_type = 'bank_account' if payment_method == 'card' else 'orange_money'
                    saved_payment_method = payment_method_service.get_payment_method(
                        user, payment_method_id, method_type=method_type
                    )
                    # Build account_details from saved method
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
                        "error": f"Payment method not found or invalid: {str(e)}",
                        "code": "payment_method_not_found"
                    }

            # Transaction creation
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

            # PROTECTION: Immediate balance debit to avoid duplications (Race Condition)
            wallet.subtract_balance(total_deduct)
            transaction.balance_adjusted = True

            # Store payment details
            if payment_method == 'card':
                transaction.card_last_four = account_details.get('account_number', '')[-4:] if account_details.get('account_number') else None
            elif payment_method == 'orange_money':
                transaction.orange_money_number = account_details.get('phone_number')

            transaction.save()
            
            # Save payment method if requested
            if save_payment_method and not saved_payment_method:
                try:
                    if payment_method == 'card':
                        new_payment_method = payment_method_service.create_bank_account_payment_method(
                            user=user,
                            label=payment_method_label or f"Account {account_details.get('account_number', '')[-4:]}",
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
                            label=payment_method_label or "My Orange Money",
                            orange_money_number=account_details.get('phone_number'),
                            is_default=False
                        )
                    transaction.payment_method_saved = new_payment_method
                    transaction.save()
                except Exception as e:
                    logger.exception("failed_to_save_payment_method", user_id=str(user.id))

        # FLUTTERWAVE CALL (Outside DB lock to avoid blocking the row too long)
        # Prepare recipient_details according to Flutterwave format
        recipient_details = None
        if payment_method == 'card':
            # Withdrawal to bank account
            recipient_details = {
                "account_number": account_details.get('account_number'),
                "bank_code": account_details.get('bank_code'),
                "account_name": account_details.get('account_name'),
                "type": account_details.get('type', 'bank_account')
            }
            if account_details.get('bank_country'):
                recipient_details["bank_country"] = account_details['bank_country']
        elif payment_method == 'orange_money':
            # Extract national number and country code separately
            # Use either full msisdn or orange_money_number
            full_phone = account_details.get('phone_number') or user.full_phone_number
            # Reuse same logic as deposit for safety
            from Accounts.utils import AuthUtils
            country_code, national_phone = AuthUtils.parse_phone_number(full_phone)
            
            recipient_details = {
                "phone": national_phone,
                "name": account_details.get('beneficiary_name') or f"{user.first_name} {user.last_name}".strip(),
                "country_code": country_code.replace('+', '')
            }
        
        flutterwave_result = flutterwave_service.initiate_withdrawal(
            amount=float(amount_dec),  # Conversion to float from Decimal
            payment_method=payment_method,
            recipient_details=recipient_details,
            narration=f"Wallet withdrawal - Transaction {transaction.id.hex[:8]}"
        )

        if not flutterwave_result["success"]:
            # RESTORE BALANCE on immediate failure
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

        # Update transaction
        transaction.flutterwave_reference = flutterwave_result["reference"]
        # Use charge_id for deposits (card or Orange Money)
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
        Processes a Flutterwave webhook with idempotency check.

        Args:
            flutterwave_data: Webhook data

        Returns:
            dict: Processing result
        """
        event_type = flutterwave_data.get("event")
        data = flutterwave_data.get("data", {})
        event_id = flutterwave_data.get("id")  # Unique webhook event ID
        
        # IDEMPOTENCY: Check if this event has already been processed
        if event_id:
            existing_transaction = Transaction.objects.filter(
                flutterwave_event_id=event_id
            ).first()
            
            if existing_transaction:
                logger.info(
                    "webhook_already_processed",
                    event_id=event_id,
                    transaction_id=str(existing_transaction.id),
                    event_type=event_type
                )
                return {
                    "success": True, 
                    "message": "Event already processed (idempotency)",
                    "transaction_id": str(existing_transaction.id)
                }

        if event_type == "charge.completed":
            return WalletService._process_payment_webhook(data, event_id)
        elif event_type == "transfer.completed":
            return WalletService._process_transfer_webhook(data, event_id)
        else:
            logger.info("webhook_ignored", event_type=event_type)
            return {"success": True, "message": "Event ignored"}

    @staticmethod
    def _process_payment_webhook(data, event_id=None):
        """Processes a payment webhook (deposit)"""
        tx_ref = data.get("tx_ref")
        status = data.get("status")
        flutterwave_id = str(data.get("id"))

        try:
            transaction = Transaction.objects.get(
                flutterwave_reference=tx_ref,
                transaction_type='deposit'
            )

            if status == "successful":
                # Store event_id for idempotency
                if event_id and not transaction.flutterwave_event_id:
                    transaction.flutterwave_event_id = event_id
                    transaction.save(update_fields=['flutterwave_event_id'])
                
                transaction.mark_completed()
                logger.info(
                    "deposit_completed_via_webhook",
                    transaction_id=str(transaction.id),
                    flutterwave_id=flutterwave_id,
                    event_id=event_id
                )
                
                # Deposit notification
                from Notifications.services import NotificationService
                NotificationService.send(
                    user=transaction.wallet.user,
                    title="Deposit received",
                    body=f"Your deposit of {transaction.amount_euros} {transaction.currency} has been confirmed.",
                    notification_type='transaction',
                    data={'transaction_id': str(transaction.id)},
                    channels=['push', 'email']
                )

                return {"success": True, "message": "Deposit processed successfully"}
            else:
                transaction.mark_failed(
                    error_message=f"Payment {status}",
                    error_code="payment_failed"
                )
                return {"success": True, "message": "Deposit failure recorded"}

        except Transaction.DoesNotExist:
            logger.warning("webhook_transaction_not_found", tx_ref=tx_ref)
            return {"success": False, "error": "Transaction not found"}

    @staticmethod
    def _process_transfer_webhook(data, event_id=None):
        """Processes a transfer webhook (withdrawal)"""
        reference = data.get("reference")
        status = data.get("status")

        try:
            transaction = Transaction.objects.get(
                flutterwave_reference=reference,
                transaction_type='withdrawal'
            )

            if status == "successful":
                # Store event_id for idempotency
                if event_id and not transaction.flutterwave_event_id:
                    transaction.flutterwave_event_id = event_id
                
                transaction.mark_completed()
                
                # Save additional information
                proof = data.get("payment_information", {}).get("proof")
                if proof:
                    transaction.transfer_proof = proof
                
                # Build extra_data with relevant info
                extra_info = {
                    "bank": data.get("bank"),
                    "debit_information": data.get("debit_information"),
                    "webhook_meta": data.get("meta")
                }
                # Update extra_data without overwriting if possible
                if transaction.extra_data:
                    transaction.extra_data.update(extra_info)
                else:
                    transaction.extra_data = extra_info
                
                transaction.save()

                logger.info(
                    "withdrawal_completed_via_webhook",
                    transaction_id=str(transaction.id),
                    reference=reference,
                    proof=proof,
                    event_id=event_id
                )


                # Withdrawal notification
                from Notifications.services import NotificationService
                NotificationService.send(
                    user=transaction.wallet.user,
                    title="Withdrawal confirmed",
                    body=f"Your withdrawal of {transaction.amount_euros} {transaction.currency} has been sent successfully.",
                    notification_type='transaction',
                    data={'transaction_id': str(transaction.id)},
                    channels=['push', 'email']
                )

                return {"success": True, "message": "Withdrawal processed successfully"}
            else:
                # REFUND BALANCE on transfer failure
                if transaction.balance_adjusted:
                    total_to_refund = (Decimal(transaction.amount_cents) + Decimal(transaction.fee_cents)) / 100
                    transaction.wallet.add_balance(total_to_refund)
                    transaction.balance_adjusted = False
                
                transaction.mark_failed(
                    error_message=f"Transfer {status}",
                    error_code="transfer_failed"
                )
                return {"success": True, "message": "Withdrawal failure recorded and balance refunded"}

        except Transaction.DoesNotExist:
            logger.warning("webhook_transfer_not_found", reference=reference)
            return {"success": False, "error": "Transaction not found"}

    @staticmethod
    def _validate_amount_for_currency(amount, currency):
        """
        Validates amount according to currency rules.

        Args:
            amount: Amount to validate
            currency: Currency code

        Returns:
            bool: True if valid
        """
        if amount <= 0:
            return False

        # Specific rules per currency
        if currency == 'EUR':
            return amount <= 10000  # Max 10,000€
        elif currency in ['XAF', 'XOF']:  # CFA Franc
            return amount <= 5000000  # Max 5M FCFA
        elif currency == 'NGN':
            return amount <= 5000000  # Max 5M NGN
        elif currency in ['GHS', 'KES', 'ZAR']:
            return amount <= 100000  # Max 100k in these currencies
        else:
            return amount <= 10000  # Default

    @staticmethod
    def _calculate_deposit_fee(amount, payment_method, currency):
        """
        Calculates deposit fees based on method and currency.

        Args:
            amount: Deposit amount
            payment_method: 'card' or 'orange_money'
            currency: Currency code

        Returns:
            Decimal: Fee amount
        """
        if payment_method == 'card':
            # Card fee: 2.9% + fixed fee per currency
            fee_rate = Decimal('0.029')
            if currency == 'EUR':
                fixed_fee = Decimal('0.25')
            elif currency in ['XAF', 'XOF']:
                fixed_fee = Decimal('200')  # 200 FCFA
            elif currency == 'NGN':
                fixed_fee = Decimal('100')  # 100 NGN
            else:
                fixed_fee = Decimal('1')  # 1 unit by default
        else:  # orange_money
            # Mobile money fee: 5%
            fee_rate = Decimal('0.05')
            fixed_fee = Decimal('0')

        return (amount * fee_rate) + fixed_fee

    @staticmethod
    def _calculate_withdrawal_fee(amount, payment_method, currency):
        """
        Calculates withdrawal fees based on method and currency.

        Args:
            amount: Withdrawal amount
            payment_method: 'card' or 'orange_money'
            currency: Currency code

        Returns:
            Decimal: Fee amount
        """
        if payment_method == 'card':
            # Card fee: 3% + fixed fee
            fee_rate = Decimal('0.03')
            if currency == 'EUR':
                fixed_fee = Decimal('0.50')
            elif currency in ['XAF', 'XOF']:
                fixed_fee = Decimal('300')  # 300 FCFA
            elif currency == 'NGN':
                fixed_fee = Decimal('200')  # 200 NGN
            else:
                fixed_fee = Decimal('2')  # 2 units by default
        else:  # orange_money
            # Mobile money fee: 6%
            fee_rate = Decimal('0.06')
            fixed_fee = Decimal('0')

        return (amount * fee_rate) + fixed_fee

    @staticmethod
    def _get_currency_symbol(currency):
        """Returns the currency symbol"""
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
        """Returns the full currency name"""
        names = {
            'EUR': 'Euro',
            'XAF': 'CFA Franc (CEMAC)',
            'XOF': 'CFA Franc (BCEAO)',
            'NGN': 'Nigerian Naira',
            'GHS': 'Ghanaian Cedi',
            'KES': 'Kenyan Shilling',
            'ZAR': 'South African Rand',
            'TZS': 'Tanzanian Shilling',
            'UGX': 'Ugandan Shilling',
            'RWF': 'Rwandan Franc',
            'BIF': 'Burundian Franc',
            'ZMW': 'Zambian Kwacha',
            'ZWD': 'Zimbabwean Dollar',
        }
        return names.get(currency, currency)

    @staticmethod
    def confirm_deposit(user, transaction_id, confirmation_data=None):
        """
        Confirms a deposit.

        Args:
            user: User instance
            transaction_id: Transaction UUID
            confirmation_data: Confirmation data

        Returns:
            dict: Result of the operation
        """
        try:
            # Transaction retrieval (global for staff, scoped to wallet for normal user)
            if user.is_staff or user.is_superuser:
                transaction = Transaction.objects.get(
                    id=transaction_id,
                    transaction_type='deposit'
                )
            else:
                wallet = WalletService.get_or_create_wallet(user)
                transaction = wallet.transactions.get(
                    id=transaction_id,
                    transaction_type='deposit'
                )

            # Status check
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Cannot confirm a {transaction.get_status_display()} deposit",
                    "code": "invalid_status"
                }

            with db_transaction.atomic():
                # Calculate amount to credit
                amount_to_credit = Decimal(str(transaction.amount_cents)) / Decimal('100')

                # Mark transaction as completed (this automatically credits the wallet)
                transaction.mark_completed()
                transaction.completed_at = timezone.now()
                transaction.save()

                # Refresh wallet to get updated balance
                transaction.wallet.refresh_from_db()

                logger.info(
                    "deposit_confirmed",
                    user_id=str(user.id),
                    transaction_id=str(transaction.id),
                    amount=amount_to_credit,
                    wallet_balance=transaction.wallet.balance
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "amount_credited": amount_to_credit,
                    "wallet_balance": transaction.wallet.balance
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.error("deposit_confirmation_error", error=str(e), transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Error during confirmation",
                "code": "confirmation_error"
            }

    @staticmethod
    def cancel_deposit(user, transaction_id, cancellation_data):
        """
        Cancels a deposit.

        Args:
            user: User instance
            transaction_id: Transaction UUID
            cancellation_data: Cancellation data

        Returns:
            dict: Result of the operation
        """
        try:
            # Retrieve wallet
            wallet = WalletService.get_or_create_wallet(user)

            # Retrieve transaction
            transaction = wallet.transactions.get(
                id=transaction_id,
                transaction_type='deposit'
            )

            # Status check
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Cannot cancel a {transaction.get_status_display()} deposit",
                    "code": "invalid_status"
                }

            with db_transaction.atomic():
                # Cancel the transaction
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
                    "refund_amount": 0  # No refund for cancelled deposits
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.exception("deposit_cancellation_error", transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Error during cancellation",
                "code": "cancellation_error"
            }

    @staticmethod
    def confirm_withdrawal(user, transaction_id, confirmation_data=None):
        """
        Confirms a withdrawal.

        Args:
            user: User instance
            transaction_id: Transaction UUID
            confirmation_data: Confirmation data

        Returns:
            dict: Result of the operation
        """
        try:
            # Transaction retrieval (global for staff, scoped to wallet for normal user)
            if user.is_staff or user.is_superuser:
                transaction = Transaction.objects.get(
                    id=transaction_id,
                    transaction_type='withdrawal'
                )
            else:
                wallet = WalletService.get_or_create_wallet(user)
                transaction = wallet.transactions.get(
                    id=transaction_id,
                    transaction_type='withdrawal'
                )

            # Status check
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Cannot confirm a {transaction.get_status_display()} withdrawal",
                    "code": "invalid_status"
                }

            # Mark as completed (debit was already done at initiation)
            with db_transaction.atomic():
                transaction.status = 'completed'
                transaction.completed_at = timezone.now()
                transaction.save()

                logger.info(
                    "withdrawal_confirmed",
                    user_id=str(user.id),
                    transaction_id=str(transaction.id),
                    amount=Decimal(str(transaction.amount_cents)) / Decimal('100'),
                    wallet_balance=transaction.wallet.balance
                )

                return {
                    "success": True,
                    "transaction": transaction,
                    "amount_debited": Decimal(str(transaction.amount_cents)) / Decimal('100'),
                    "wallet_balance": transaction.wallet.balance
                }

        except Transaction.DoesNotExist:
            return {
                "success": False,
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.exception("withdrawal_confirmation_error", transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Error during confirmation",
                "code": "confirmation_error"
            }

    @staticmethod
    def cancel_withdrawal(user, transaction_id, cancellation_data):
        """
        Cancels a withdrawal and refunds the wallet.

        Args:
            user: User instance
            transaction_id: Transaction UUID
            cancellation_data: Cancellation data

        Returns:
            dict: Result of the operation
        """
        try:
            # Retrieve wallet
            wallet = WalletService.get_or_create_wallet(user)

            # Retrieve transaction
            transaction = wallet.transactions.get(
                id=transaction_id,
                transaction_type='withdrawal'
            )

            # Status check
            if transaction.status not in ['pending', 'processing']:
                return {
                    "success": False,
                    "error": f"Cannot cancel a {transaction.get_status_display()} withdrawal",
                    "code": "invalid_status"
                }

            with db_transaction.atomic():
                # Calculate amount to refund (amount + fees)
                total_amount = Decimal(str(transaction.amount_cents + transaction.fee_cents)) / Decimal('100')

                # Refund the wallet
                wallet.add_balance(total_amount)

                # Cancel the transaction
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
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.exception("withdrawal_cancellation_error", transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Error during cancellation",
                "code": "cancellation_error"
            }

    @staticmethod
    def check_transaction_status(transaction):
        """
        Checks transaction status with Flutterwave.

        Args:
            transaction: Transaction instance

        Returns:
            dict: Transaction status
        """
        try:
            if not transaction.flutterwave_transaction_id:
                return {
                    "success": False,
                    "error": "Flutterwave Transaction ID missing",
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
                # Map Flutterwave status to our status
                flutterwave_status = result.get("flutterwave_status", result.get("status"))
                mapped_status = result.get("status")  # Already mapped by verify_transaction/verify_transfer
                
                # Update local status if necessary
                if mapped_status == "completed" and transaction.status != "completed":
                    # Successful transaction on Flutterwave side, confirm it
                    if transaction.transaction_type == 'deposit':
                        WalletService.confirm_deposit(transaction.wallet.user, transaction.id)
                    else:
                        WalletService.confirm_withdrawal(transaction.wallet.user, transaction.id)
                    # Refresh transaction
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
                "error": "Error during status check",
                "code": "status_check_error"
            }

    @staticmethod
    def update_transaction_status(transaction_id, new_status, update_data=None):
        """
        Updates transaction status (admin).

        Args:
            transaction_id: Transaction UUID
            new_status: New status
            update_data: Additional data

        Returns:
            dict: Result of the operation
        """
        try:
            transaction = Transaction.objects.get(id=transaction_id)
            old_status = transaction.status

            # Status transition validation
            valid_transitions = {
                'pending': ['processing', 'completed', 'failed', 'cancelled'],
                'processing': ['completed', 'failed', 'cancelled'],
                'completed': [],  # Cannot change once completed
                'failed': ['pending'],  # Can be restarted
                'cancelled': ['pending']  # Can be restarted
            }

            if new_status not in valid_transitions.get(old_status, []):
                return {
                    "success": False,
                    "error": f"Invalid status transition: {old_status} -> {new_status}",
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
                        reason=update_data.get("notes", "Manually cancelled"),
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
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }
        except Exception as e:
            logger.error("transaction_status_update_error", error=str(e), transaction_id=str(transaction_id))
            return {
                "success": False,
                "error": "Error during status update",
                "code": "status_update_error"
            }

    @staticmethod
    def get_wallet_statistics():
        """
        Returns global wallet statistics.

        Returns:
            dict: Statistics
        """
        try:
            total_wallets = Wallet.objects.count()
            total_balance = Wallet.objects.aggregate(
                total=Sum('balance_cents')
            )['total'] or 0
            # Convert from cents to units
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

            # Volume by currency
            volume_by_currency = {}
            for currency_data in Transaction.objects.filter(status='completed').values('currency').annotate(
                volume=Sum('amount_cents'),
                count=Count('id')
            ):
                currency = currency_data['currency']
                volume_by_currency[currency] = {
                    'volume': currency_data['volume'] / 100,  # Convert to units
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
                "error": "Error during statistics generation",
                "generated_at": timezone.now().isoformat()
            }


# Global service instance
wallet_service = WalletService()