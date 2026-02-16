import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction as db_transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import F

from .models import Offer, EscrowLock, AuditLog
from Wallet.models import Wallet, Transaction
from Wallet.Services.wallet_service import WalletService
import structlog

logger = structlog.get_logger(__name__)

class SecureEscrowService:
    """
    Ultra-secure service for P2P Escrow management.
    Implements 'Security.pdf' specifications.
    """

    @staticmethod
    def create_offer(user, amount_sell, currency_sell, amount_buy, currency_buy, beneficiary_data=None, expiry_hours=24):
        """
        Creates an exchange offer.
        First verifies the user has available funds (Read-only, no lock here).
        """
        # 1. Vérification KYC
        # if user.kyc_status != 'verified':
        #     raise ValidationError("KYC requis pour créer une offre.")
        # 1. KYC Verification
        if user.kyc_status != 'verified':
            raise ValidationError("KYC required to create an offer.")

        with db_transaction.atomic():
            # 2. Lock the wallet to prevent concurrent 'available balance' checks bypass
            wallet = Wallet.objects.select_for_update().get(user=user)
            
            # Recalculate locked amount INSIDE the lock for absolute consistency
            locked_amount = EscrowLock.objects.filter(
                user=user, 
                currency=currency_sell, 
                status='LOCKED'
            ).aggregate(sum=models.Sum('amount_cents'))['sum'] or 0
            
            real_balance = wallet.balance_cents
            available_balance = real_balance - locked_amount
            
            amount_sell_cents = int(Decimal(str(amount_sell)) * 100)
            
            if available_balance < amount_sell_cents:
                 raise ValidationError(f"Insufficient available balance (Locked: {locked_amount/100}, Available: {available_balance/100})")

            amount_buy_cents = int(Decimal(str(amount_buy)) * 100)
            rate = Decimal(amount_buy) / Decimal(amount_sell)

            offer = Offer.objects.create(
                user=user,
                amount_sell_cents=amount_sell_cents,
                currency_sell=currency_sell,
                amount_buy_cents=amount_buy_cents,
                currency_buy=currency_buy,
                rate=rate,
                beneficiary_data=beneficiary_data or {},
                expires_at=timezone.now() + timedelta(hours=expiry_hours),
                status='OPEN'
            )
        
        description = f"Created offer: Sell {amount_sell} {currency_sell} for {amount_buy} {currency_buy}"
        SecureEscrowService._log_audit(
            action="OFFER_CREATED",
            user=user,
            offer=offer,
            data={"description": description}
        )
        
        return offer

    @staticmethod
    def accept_offer(user_accepter, offer_id, beneficiary_data=None):
        """
        A2 accepts A1's offer.
        beneficiary_data = B1 (A2's friend/beneficiary)
        """
        # Transaction Atomique Globale - DOIT englober select_for_update()
        with db_transaction.atomic():
            try:
                offer = Offer.objects.select_for_update().get(id=offer_id)
            except Offer.DoesNotExist:
                raise ValidationError("Offre introuvable")

            if offer.status != 'OPEN':
                raise ValidationError(f"Offre non disponible (Statut: {offer.status})")
                
            if offer.user == user_accepter:
                raise ValidationError("Impossible d'accepter sa propre offre")

            # if user_accepter.kyc_status != 'verified':
            #     raise ValidationError("KYC requis pour accepter une offre.")
                
            # A1 = offer.user (Vendeur initial)
            # A2 = user_accepter (Acheteur)
            
            # 1. Validation de sécurité : Devise du bénéficiaire B1 (celui qui reçoit currency_sell)
            SecureEscrowService._validate_beneficiary(beneficiary_data or {}, offer.currency_sell)
            
            user_a1 = offer.user
            user_a2 = user_accepter
            
            # Montants à bloquer
            amount_lock_a1 = offer.amount_sell_cents # XOF
            amount_lock_a2 = offer.amount_buy_cents  # EUR
            # 1. Verrouillage + Vérification Solde A1 (Optimistic + DB Lock)
            SecureEscrowService._atomic_lock_funds(
                user=user_a1, 
                amount_cents=amount_lock_a1, 
                currency=offer.currency_sell,
                offer=offer
            )
            
            # 2. Locking + Balance check A2
            SecureEscrowService._atomic_lock_funds(
                user=user_a2, 
                amount_cents=amount_lock_a2, 
                currency=offer.currency_buy,
                offer=offer
            )
            
            # 3. Offer Update
            # Status ACCEPTED: Funds locked, but waiting for Seller (A1) final validation to specify beneficiary.
            offer.status = 'ACCEPTED'
            offer.accepted_by = user_a2
            offer.accepted_at = timezone.now()
            offer.accepted_beneficiary_data = beneficiary_data or {}
            offer.save()
            
            # 4. Audit
            SecureEscrowService._log_audit(
                action="OFFER_LOCKED", 
                user=user_a2, 
                offer=offer,
                data={
                    "a1_locked": f"{amount_lock_a1} {offer.currency_sell}",
                    "a2_locked": f"{amount_lock_a2} {offer.currency_buy}",
                    "b1_info": beneficiary_data
                }

            )

            # Notification to A1 (Seller)
            from Notifications.services import NotificationService
            NotificationService.send(
                user=user_a1,
                title="Offer accepted!",
                body=f"Your offer of {offer.amount_sell} {offer.currency_sell} was accepted. Please validate the beneficiary to finalize.",
                notification_type='offer',
                data={'offer_id': str(offer.id), 'screen': 'offer_detail'},
                channels=['push', 'email']
            )
            
        return offer

    @staticmethod
    def validate_offer(user_validator, offer_id, beneficiary_data=None):
        """
        A1 validates A2's acceptance and adds beneficiary info (B2).
        Transition from ACCEPTED -> LOCKED.
        """
        try:
            offer = Offer.objects.select_for_update().get(id=offer_id)
        except Offer.DoesNotExist:
             raise ValidationError("Offer not found")

        if offer.status != 'ACCEPTED':
             raise ValidationError(f"Offer is not awaiting validation (Status: {offer.status})")
        
        if offer.user != user_validator:
             raise ValidationError("Only the offer creator can validate it")

        # 1. Security validation: Beneficiary B2's currency (the one receiving currency_buy)
        SecureEscrowService._validate_beneficiary(beneficiary_data or {}, offer.currency_buy)

        offer.beneficiary_data = beneficiary_data or {}
        offer.status = 'LOCKED'
        offer.save()
        
        SecureEscrowService._log_audit(
            action="OFFER_VALIDATED",
            user=user_validator,
            offer=offer,
            data={"b2_info": beneficiary_data}
        )
        
        # Notification to BENEFICIARIES (B1 and B2) for validation
        b1_phone = offer.accepted_beneficiary_data.get('phone')
        b2_phone = offer.beneficiary_data.get('phone')
        
        b1_user = SecureEscrowService._get_user_by_phone(b1_phone)
        b2_user = SecureEscrowService._get_user_by_phone(b2_phone)
        
        if b1_user:
            NotificationService.send(
                user=b1_user,
                title="Action Required: P2P Exchange",
                body=f"You have been designated as the beneficiary for an exchange of {offer.amount_sell} {offer.currency_sell}. Please confirm to receive funds.",
                notification_type='offer',
                data={'offer_id': str(offer.id), 'screen': 'offer_detail'},
                channels=['push', 'sms']
            )
            
        if b2_user:
            NotificationService.send(
                user=b2_user,
                title="Action Required: P2P Exchange",
                body=f"You have been designated as the beneficiary for an exchange of {offer.amount_buy} {offer.currency_buy}. Please confirm to receive funds.",
                notification_type='offer',
                data={'offer_id': str(offer.id), 'screen': 'offer_detail'},
                channels=['push', 'sms']
            )
        
        return offer

    @staticmethod
    def _atomic_lock_funds(user, amount_cents, currency, offer):
        """
        Internal method to lock funds with Double-Spend protection.
        Uses 'select_for_update' on the Wallet.
        """
        wallet = Wallet.objects.select_for_update().get(user=user)
        
        # Currency Verification
        # Note: Wallet has one main currency.
        # If we support multi-currency per user, we need a separate WalletBalance table.
        # For this POC, we assume Wallet.currency must match.
        if wallet.currency != currency:
             raise ValidationError(f"{user}'s wallet ({wallet.currency}) does not match required currency ({currency})")

        # Calculate available balance (Real balance - existing locks)
        # We must recount locks because we are in a transaction
        current_locks = EscrowLock.objects.filter(
            user=user, status='LOCKED'
        ).aggregate(sum=models.Sum('amount_cents'))['sum'] or 0
        
        available = wallet.balance_cents - current_locks
        
        if available < amount_cents:
            raise ValidationError(f"Insufficient balance for {user}. Required: {amount_cents}, Available: {available}")
            
        # Lock Creation (Proof of blocking)
        lock_hash = SecureEscrowService._calculate_hash(user.id, amount_cents, offer.id)
        
        lock = EscrowLock.objects.create(
            offer=offer,
            user=user,
            amount_cents=amount_cents,
            currency=currency,
            status='LOCKED',
            expires_at=timezone.now() + timedelta(hours=24), # Auto-rollback after 24h
            lock_hash=lock_hash
        )
        
        # Optimistic version update (Optional but recommended by Security.pdf)
        Wallet.objects.filter(pk=wallet.pk).update(version=F('version') + 1)
        
        return lock

    @staticmethod
    def confirm_transaction(offer_id):
        """
        Finalizes the exchange (Phase 7 of the PDF).
        Releases locked funds to beneficiaries.
        DEADLOCK PREVENTION: Deterministic locking of the 4 wallets.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status != 'LOCKED':
                 raise ValidationError("Transaction cannot be finalized (Not in LOCKED status)")

            # Retrieve active Locks
            locks = EscrowLock.objects.filter(offer=offer, status='LOCKED')
            if locks.count() != 2:
                 raise ValidationError("Inconsistency: Incorrect lock count (Expected 2)")

            user_a1 = offer.user # Seller XOF
            user_a2 = offer.accepted_by # Buyer EUR
            
            # --- ACTOR IDENTIFICATION ---
            lock_a1 = locks.get(user=user_a1)
            b1_phone = offer.accepted_beneficiary_data.get('phone')
            if not b1_phone:
                 raise ValidationError("Beneficiary B1 missing for XOF flow")
            
            b1_user = SecureEscrowService._get_user_by_phone(b1_phone)
            if not b1_user:
                 raise ValidationError(f"User B1 not found with number {b1_phone}")
            
            lock_a2 = locks.get(user=user_a2)
            b2_phone = offer.beneficiary_data.get('phone')
            if not b2_phone:
                 raise ValidationError("Beneficiary B2 missing for EUR flow")
            
            b2_user = SecureEscrowService._get_user_by_phone(b2_phone)
            if not b2_user:
                 raise ValidationError(f"User B2 not found with number {b2_phone}")

            # --- DETERMINISTIC LOCKING (Global Lock) ---
            # We retrieve the IDs of the involved users to lock their wallets in ascending order
            # This prevents deadlocks if multiple cross transactions occur
            involved_users = sorted([user_a1.id, user_a2.id, b1_user.id, b2_user.id])
            
            # We force wallet locking via select_for_update
            # Note: We use filter(user_id__in=...) to make a grouped request, but
            # to guarantee DB locking order, it's often safer to make individual sorted requests
            # or hope the DB handles row-level locking intelligently.
            # With PostgreSQL, SELECT ... FOR UPDATE locks rows as they are visited via the index.
            # To be 100% sure: loop on sorted IDs.
            
            wallets_map = {}
            for uid in involved_users:
                # get_or_create to ensure it exists
                w, _ = Wallet.objects.get_or_create(user_id=uid)
                # Explicit locking
                Wallet.objects.select_for_update().get(pk=w.pk)
                wallets_map[uid] = w

            # --- SWAP EXECUTION ---
            
            # 1. XOF flow management (A1 -> B1)
            wallet_a1 = wallets_map[user_a1.id]
            wallet_b1 = wallets_map[b1_user.id]
            
            # --- CURRENCY SAFETY CHECK ---
            if wallet_b1.currency != lock_a1.currency:
                raise ValidationError(f"B1 Currency mismatch: Expected {lock_a1.currency}, Received {wallet_b1.currency}")
            
            # Debit A1
            amt_a1 = Decimal(lock_a1.amount_cents) / 100
            wallet_a1.subtract_balance(amt_a1)
            # Credit B1
            wallet_b1.add_balance(amt_a1)
            
            # History A1
            Transaction.objects.create(
                wallet=wallet_a1,
                transaction_type='p2p_debit',
                amount_cents=lock_a1.amount_cents,
                currency=lock_a1.currency,
                status='completed',
                payment_method='internal',
                balance_adjusted=True,
                extra_data={"offer_id": str(offer.id), "role": "sender", "counterparty": b1_phone}
            )
            # History B1
            Transaction.objects.create(
                wallet=wallet_b1,
                transaction_type='p2p_credit',
                amount_cents=lock_a1.amount_cents,
                currency=lock_a1.currency,
                status='completed',
                payment_method='internal',
                balance_adjusted=True,
                extra_data={"offer_id": str(offer.id), "role": "receiver", "sender_phone": user_a1.full_phone_number}
            )

            lock_a1.status = 'RELEASED'
            lock_a1.released_at = timezone.now()
            lock_a1.save()

            # 2. EUR flow management (A2 -> B2)
            wallet_a2 = wallets_map[user_a2.id]
            wallet_b2 = wallets_map[b2_user.id]
            
            # --- CURRENCY SAFETY CHECK ---
            if wallet_b2.currency != lock_a2.currency:
                raise ValidationError(f"B2 Currency mismatch: Expected {lock_a2.currency}, Received {wallet_b2.currency}")
            
            # Debit A2
            amt_a2 = Decimal(lock_a2.amount_cents) / 100
            wallet_a2.subtract_balance(amt_a2)
            # Credit B2
            wallet_b2.add_balance(amt_a2)
            
            # History A2
            Transaction.objects.create(
                wallet=wallet_a2,
                transaction_type='p2p_debit',
                amount_cents=lock_a2.amount_cents,
                currency=lock_a2.currency,
                status='completed',
                payment_method='internal',
                balance_adjusted=True,
                extra_data={"offer_id": str(offer.id), "role": "sender", "counterparty": b2_phone}
            )
            # History B2
            Transaction.objects.create(
                wallet=wallet_b2,
                transaction_type='p2p_credit',
                amount_cents=lock_a2.amount_cents,
                currency=lock_a2.currency,
                status='completed',
                payment_method='internal',
                balance_adjusted=True,
                extra_data={"offer_id": str(offer.id), "role": "receiver", "sender_phone": user_a2.full_phone_number}
            )

            lock_a2.status = 'RELEASED'
            lock_a2.released_at = timezone.now()
            lock_a2.save()
            
            # Offer Update
            offer.status = 'COMPLETED'
            offer.save()
            
            SecureEscrowService._log_audit(
                action="OFFER_COMPLETED",
                user=user_a1, 
                offer=offer,
                data={
                    "status": "SWAP_EXECUTED",
                    "flow_xof": f"A1->B1 ({lock_a1.amount_cents})",
                    "flow_eur": f"A2->B2 ({lock_a2.amount_cents})"
                }
            )

            # Success notification to both parties
            from Notifications.services import NotificationService
            
            # A1 sold (Debited) -> Success selling notification
            NotificationService.send(
                user=user_a1,
                title="Exchange Successful!",
                body=f"Sale of {offer.amount_sell} {offer.currency_sell} completed successfully.",
                notification_type='transaction',
                data={'offer_id': str(offer.id)},
                channels=['push', 'email']
            )

            # A2 bought (Debited) -> Success buying notification
            NotificationService.send(
                user=user_a2,
                title="Exchange Successful!",
                body=f"Purchase of {offer.amount_buy} {offer.currency_buy} completed successfully.",
                notification_type='transaction',
                data={'offer_id': str(offer.id)},
                channels=['push', 'email']
            )

    @staticmethod
    def _get_user_by_phone(phone):
        from Accounts.models import User
        import phonenumbers
        from phonenumbers import PhoneNumberFormat
        
        # Number normalization (E.164)
        try:
            # If the number does not start with +, we try to guess or assume it's already formatted
            # For robustness, we parse the number
            parsed = phonenumbers.parse(phone, None)
            if phonenumbers.is_valid_number(parsed):
                phone = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        except Exception:
            # If parsing fails, we keep the number as is (case where it's already a special or formatted ID)
            pass

        try:
             return User.objects.get(full_phone_number=phone)
        except User.DoesNotExist:
             return None

    @staticmethod
    def _validate_beneficiary(beneficiary_data, expected_currency):
        """
        ✅ NEW: Validates beneficiary data and ensures currency matches.
        """
        phone = beneficiary_data.get('phone')
        if not phone:
            raise ValidationError("Beneficiary phone number is required")
            
        user = SecureEscrowService._get_user_by_phone(phone)
        if not user:
            raise ValidationError(f"Beneficiary user with phone {phone} not found")
            
        # Wallet currency verification
        wallet = Wallet.objects.filter(user=user).first()
        if not wallet or wallet.currency != expected_currency:
             raise ValidationError(
                 f"Beneficiary currency ({wallet.currency if wallet else 'N/A'}) "
                 f"does not match required currency for this flow ({expected_currency})"
             )
        
        return user

    @staticmethod
    def cancel_transaction(offer_id, reason="User Cancelled"):
        """
        Cancels the exchange and releases funds (Rollback).
        Can be triggered by timeout or admin.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status not in ['LOCKED', 'OPEN', 'ACCEPTED']:
                # If already completed or cancelled, do nothing
                return

            offer.status = 'CANCELLED'
            offer.save()
            
            # If funds were locked, release them (Rollback)
            locks = EscrowLock.objects.filter(offer=offer, status='LOCKED')
            for lock in locks:
                lock.status = 'ROLLEDBACK'
                lock.released_at = timezone.now()
                lock.save()
                # No real money movement necessary because the Lock was "virtual" 
                # (Subtracted from "available" balance by calculation, but present in "balance_cents").
                # Money becomes available automatically because the lock is no longer 'LOCKED' status.
            
            SecureEscrowService._log_audit(
                action="OFFER_CANCELLED",
                user=offer.user,
                offer=offer,
                data={"reason": reason}
            )

    @staticmethod
    def confirm_beneficiary_participation(user, offer_id):
        """
        Allows a beneficiary (B1 or B2) to confirm participation.
        If both confirm, the swap is executed.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status != 'LOCKED':
                raise ValidationError("Offer must be in LOCKED status for beneficiary confirmation.")
                
            b1_phone = offer.accepted_beneficiary_data.get('phone')
            b2_phone = offer.beneficiary_data.get('phone')
            
            is_b1 = (user.full_phone_number == b1_phone)
            is_b2 = (user.full_phone_number == b2_phone)
            
            if not is_b1 and not is_b2:
                raise ValidationError("You are not a designated beneficiary for this offer.")
            
            # Update flags
            if is_b1:
                offer.b1_confirmed = True
            if is_b2:
                offer.b2_confirmed = True
            
            offer.save()
            
            SecureEscrowService._log_audit(
                action="BENEFICIARY_CONFIRMED",
                user=user,
                offer=offer,
                data={"is_b1": is_b1, "is_b2": is_b2}
            )
            
            # If both confirmed, finalize
            if offer.b1_confirmed and offer.b2_confirmed:
                SecureEscrowService.confirm_transaction(offer_id)
                logger.info("p2p_swap_auto_executed", offer_id=str(offer_id))
            
            return offer

    @staticmethod
    def dispute_transaction(offer_id, user, reason):
        """
        Reports a dispute on an ongoing transaction.
        Freezes all fund movements.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            # Dispute can be opened if LOCKED (funds frozen) or COMPLETED (to report non-receipt)
            if offer.status not in ['LOCKED', 'COMPLETED']:
                 raise ValidationError("Cannot open a dispute for this offer")

            # Only stakeholders can open a dispute
            if user != offer.user and user != offer.accepted_by:
                 raise ValidationError("Unauthorized")

            previous_status = offer.status
            offer.status = 'DISPUTE'
            offer.save()
            
            SecureEscrowService._log_audit(
                action="OFFER_DISPUTED",
                user=user,
                offer=offer,
                data={
                    "reason": reason,
                    "previous_status": previous_status
                }
            )
            return offer

    @staticmethod
    def resolve_dispute(offer_id, resolved_by, outcome, notes=None):
        """
        Resolves an Admin Dispute.
        outcome: 'RELEASE_TO_BUYER', 'RELEASE_TO_SELLER', 'CANCEL_BOTH'
    """
        if not resolved_by.is_staff:
            raise ValidationError("Only an administrator can resolve a dispute.")

        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            if offer.status != 'DISPUTE':
                raise ValidationError("Offer is not in dispute.")

            if outcome == 'RELEASE_TO_SELLER':
                # Force transaction completion (Phase 7)
                # Note: confirm_transaction already handles deterministic locking
                SecureEscrowService.confirm_transaction(offer_id)
            
            elif outcome == 'CANCEL_BOTH':
                # Cancel and release funds (Rollback phase)
                SecureEscrowService.cancel_transaction(offer_id, reason=f"Dispute resolved: {notes}")
            
            elif outcome == 'RELEASE_TO_BUYER':
                # Specific logic if we want to favor the buyer (rare in this direct P2P flow)
                # For now we consider 'CANCEL_BOTH' as return to sender.
                SecureEscrowService.cancel_transaction(offer_id, reason=f"Dispute resolved (Refund): {notes}")
            
            SecureEscrowService._log_audit(
                action="OFFER_DISPUTE_RESOLVED",
                user=resolved_by,
                offer=offer,
                data={
                    "outcome": outcome,
                    "notes": notes
                }
            )
            return offer

    @staticmethod
    def _calculate_hash(user_id, amount, offer_id):
        """Generates a SHA256 hash for lock integrity"""
        raw = f"{user_id}:{amount}:{offer_id}:{timezone.now().isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _log_audit(action, user, offer, data):
        """Immutable log with hash chaining"""
        # Retrieve last hash
        last_log = AuditLog.objects.order_by('-timestamp').first()
        prev_hash = last_log.hash if last_log else "GENESIS_HASH"
        
        # Calculate new hash
        raw_content = f"{prev_hash}:{action}:{user.id}:{json.dumps(data, sort_keys=True)}"
        current_hash = hashlib.sha256(raw_content.encode()).hexdigest()
        
        AuditLog.objects.create(
            action=action,
            user_id=str(user.id),
            offer_id=str(offer.id) if offer else None,
            details=data,
            previous_hash=prev_hash,
            hash=current_hash,
            amount_cents=data.get('amount_cents'), # Optional
            currency=data.get('currency')
        )

    # ✅ NEW: Dispute management
    @staticmethod
    def initiate_dispute(offer_id, user_initiator, reason, evidence=None):
        """
        ✅ NEW: Initiates a dispute on an offer.
        Allows one of the parties to contest a transaction.
        
        Args:
            offer_id: Offer UUID
            user_initiator: Initiating user (A1 or A2)
            reason: Dispute reason (max 500 chars)
            evidence: Optional dict with screenshots/messages
        
        Returns:
            Dispute object
        """
        from .models import Dispute
        
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            # Verify user is one of the parties
            if user_initiator not in [offer.user, offer.accepted_by]:
                raise ValidationError("You are not a party to this offer")
            
            # Verify offer is in appropriate state
            if offer.status not in ['LOCKED', 'RELEASED_TO_SELLER', 'RELEASED_TO_BUYER']:
                raise ValidationError(f"Cannot create a dispute for an offer with status {offer.status}")
            
            # Verify no existing dispute
            existing = Dispute.objects.filter(offer=offer, status__in=['open', 'under_review']).exists()
            if existing:
                raise ValidationError("A dispute is already in progress for this offer")
            
            # Create the dispute
            dispute = Dispute.objects.create(
                offer=offer,
                initiated_by=user_initiator,
                reason=reason,
                evidence=evidence or {}
            )
            
            SecureEscrowService._log_audit(
                action="DISPUTE_INITIATED",
                user=user_initiator,
                offer=offer,
                data={
                    "dispute_id": str(dispute.id),
                    "reason": reason,
                    "initiator": str(user_initiator.id)
                }
            )
            
            logger.info(
                "dispute_initiated",
                dispute_id=str(dispute.id),
                offer_id=str(offer_id),
                initiator=str(user_initiator.id)
            )
        
        return dispute
    
    @staticmethod
    def review_dispute(dispute_id, reviewer, resolution, notes=None):
        """
        ✅ NEW: Admin reviews and resolves a dispute.
        
        Args:
            dispute_id: Dispute UUID
            reviewer: Reviewing Admin/Staff
            resolution: 'refund_a1', 'refund_a2', 'split'
            notes: Admin notes
        
        Returns:
            Dispute object
        """
        from .models import Dispute
        
        if not reviewer.is_staff:
            raise ValidationError("Only an administrator can process disputes")
        
        with db_transaction.atomic():
            dispute = Dispute.objects.select_for_update().get(id=dispute_id)
            
            if dispute.status not in ['open', 'under_review']:
                raise ValidationError(f"Dispute in {dispute.status} status, cannot be resolved")
            
            offer = dispute.offer
            
            # Implement the resolution
            try:
                if resolution == 'refund_a1':
                    # Refund A1 (user who created the offer)
                    _refund_user_for_dispute(offer.user, offer.amount_sell_cents, offer.currency_sell)
                    
                elif resolution == 'refund_a2':
                    # Refund A2 (user who accepted)
                    if offer.accepted_by:
                        _refund_user_for_dispute(offer.accepted_by, offer.amount_buy_cents, offer.currency_buy)
                    
                elif resolution == 'split':
                    # Split 50/50
                    split_amount_a1 = offer.amount_sell_cents // 2
                    split_amount_a2 = offer.amount_buy_cents // 2 if offer.accepted_by else 0
                    
                    _refund_user_for_dispute(offer.user, split_amount_a1, offer.currency_sell)
                    if offer.accepted_by:
                        _refund_user_for_dispute(offer.accepted_by, split_amount_a2, offer.currency_buy)
            
            except Exception as e:
                logger.error("dispute_resolution_error", error=str(e), dispute_id=str(dispute_id))
                raise ValidationError(f"Error during resolution: {str(e)}")
            
            # Update the dispute
            dispute.status = 'resolved'
            dispute.resolution = resolution
            dispute.reviewed_by = reviewer
            dispute.reviewed_at = timezone.now()
            dispute.admin_notes = notes or ""
            dispute.resolved_at = timezone.now()
            dispute.save()
            
            # Update the offer
            offer.status = 'CANCELLED'
            offer.save()
            
            SecureEscrowService._log_audit(
                action="DISPUTE_RESOLVED",
                user=reviewer,
                offer=offer,
                data={
                    "dispute_id": str(dispute_id),
                    "resolution": resolution,
                    "notes": notes
                }
            )
            
            logger.info(
                "dispute_resolved",
                dispute_id=str(dispute_id),
                resolution=resolution,
                reviewer=str(reviewer.id)
            )
        
        return dispute


def _refund_user_for_dispute(user, amount_cents, currency):
    """
    Utility to refund a user following a dispute resolution.
    """
    wallet = Wallet.objects.select_for_update().get(user=user)
    
    # Create a refund transaction
    transaction_obj = Transaction.objects.create(
        wallet=wallet,
        amount_cents=amount_cents,
        currency=currency,
        transaction_type='refund',
        status='completed',
        description="Dispute resolution refund",
        reference=f"DISPUTE_{timezone.now().timestamp()}"
    )
    
    # Add funds to the wallet
    wallet.balance_cents = models.F('balance_cents') + amount_cents
    wallet.save(update_fields=['balance_cents'])
    
    logger.info(
        "dispute_refund_issued",
        user_id=str(user.id),
        amount=amount_cents/100,
        currency=currency,
        transaction_id=str(transaction_obj.id)
    )
