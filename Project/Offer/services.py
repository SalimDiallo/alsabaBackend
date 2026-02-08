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
    Service ultra-sécurisé pour la gestion de l'Escrow P2P.
    Implémente les spécifications de 'Sécurité.pdf'.
    """

    @staticmethod
    def create_offer(user, amount_sell, currency_sell, amount_buy, currency_buy, beneficiary_data=None, expiry_hours=24):
        """
        Crée une offre d'échange.
        Vérifie d'abord que l'utilisateur a les fonds disponibles (Lecture seule, pas de blocage ici).
        """
        # 1. Vérification KYC
        # if user.kyc_status != 'verified':
        #     raise ValidationError("KYC requis pour créer une offre.")

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
                 raise ValidationError(f"Solde disponible insuffisant (Bloqué: {locked_amount/100}, Dispo: {available_balance/100})")

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
        A2 accepte l'offre de A1.
         beneficiary_data = B1 (Ami de A2)
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
            
            # 2. Verrouillage + Vérification Solde A2
            SecureEscrowService._atomic_lock_funds(
                user=user_a2, 
                amount_cents=amount_lock_a2, 
                currency=offer.currency_buy,
                offer=offer
            )
            
            # 3. Mise à jour Offre
            # Status ACCEPTED : Fonds bloqués, mais en attente de la validation finale du Vendeur (A1) qui doit préciser son bénéficiaire.
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

            # Notification à A1 (Vendeur)
            from Notifications.services import NotificationService
            NotificationService.send(
                user=user_a1,
                title="Offre acceptée !",
                body=f"Votre offre de {offer.amount_sell} {offer.currency_sell} a été acceptée. Veuillez valider le bénéficiaire pour finaliser.",
                notification_type='offer',
                data={'offer_id': str(offer.id), 'screen': 'offer_detail'},
                channels=['push', 'email']
            )
            
        return offer

    @staticmethod
    def validate_offer(user_validator, offer_id, beneficiary_data=None):
        """
        A1 valide l'acceptation de A2 et ajoute ses infos bénéficiaire (B2).
        Passage de ACCEPTED -> LOCKED.
        """
        # Transaction Atomique Globale - DOIT englober select_for_update()
        with db_transaction.atomic():
            try:
                offer = Offer.objects.select_for_update().get(id=offer_id)
            except Offer.DoesNotExist:
                 raise ValidationError("Offre introuvable")

            if offer.status != 'ACCEPTED':
                 raise ValidationError(f"L'offre n'est pas en attente de validation (Statut: {offer.status})")
            
            if offer.user != user_validator:
                 raise ValidationError("Seul le créateur de l'offre peut la valider")

            # 1. Validation de sécurité : Devise du bénéficiaire B2 (celui qui reçoit currency_buy)
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
            
            # Notification aux BENEFICIAIRES (B1 et B2) pour validation
            from Notifications.services import NotificationService
            b1_phone = offer.accepted_beneficiary_data.get('phone')
            b2_phone = offer.beneficiary_data.get('phone')
            
            b1_user = SecureEscrowService._get_user_by_phone(b1_phone)
            b2_user = SecureEscrowService._get_user_by_phone(b2_phone)
            
            if b1_user:
                NotificationService.send(
                    user=b1_user,
                    title="Action requise : Echange P2P",
                    body=f"Vous avez été désigné comme bénéficiaire d'un échange de {offer.amount_sell} {offer.currency_sell}. Veuillez confirmer pour recevoir les fonds.",
                    notification_type='offer',
                    data={'offer_id': str(offer.id), 'screen': 'offer_detail'},
                    channels=['push', 'sms']
                )
                
            if b2_user:
                NotificationService.send(
                    user=b2_user,
                    title="Action requise : Echange P2P",
                    body=f"Vous avez été désigné comme bénéficiaire d'un échange de {offer.amount_buy} {offer.currency_buy}. Veuillez confirmer pour recevoir les fonds.",
                    notification_type='offer',
                    data={'offer_id': str(offer.id), 'screen': 'offer_detail'},
                    channels=['push', 'sms']
                )
        
        return offer

    @staticmethod
    def _atomic_lock_funds(user, amount_cents, currency, offer):
        """
        Méthode interne pour verrouiller les fonds avec protection Double-Spend.
        Utilise 'select_for_update' sur le Wallet.
        """
        wallet = Wallet.objects.select_for_update().get(user=user)
        
        # Vérification Devise
        # Note: Le wallet a une seule devise principale.
        # Si on veut supporter multi-devises par user, il faudra une table WalletBalance séparée.
        # Pour ce POC, on assume que le Wallet.currency doit matcher.
        if wallet.currency != currency:
             raise ValidationError(f"Le wallet de {user} ({wallet.currency}) ne correspond pas à la devise requise ({currency})")

        # Calcul du solde disponible (Solde réel - Locks existants)
        # On doit recompter les locks car on est dans une transaction
        current_locks = EscrowLock.objects.filter(
            user=user, status='LOCKED'
        ).aggregate(sum=models.Sum('amount_cents'))['sum'] or 0
        
        available = wallet.balance_cents - current_locks
        
        if available < amount_cents:
            raise ValidationError(f"Solde insuffisant pour {user}. Requis: {amount_cents}, Dispo: {available}")
            
        # Création du Lock (La preuve du blocage)
        lock_hash = SecureEscrowService._calculate_hash(user.id, amount_cents, offer.id)
        
        lock = EscrowLock.objects.create(
            offer=offer,
            user=user,
            amount_cents=amount_cents,
            currency=currency,
            status='LOCKED',
            expires_at=timezone.now() + timedelta(hours=24), # Auto-rollback après 24h
            lock_hash=lock_hash
        )
        
        # Update version optimiste (Optionnel mais recommandé par Security.pdf)
        Wallet.objects.filter(pk=wallet.pk).update(version=F('version') + 1)
        
        return lock

    @staticmethod
    def confirm_transaction(offer_id):
        """
        Finalise l'échange (Phase 7 du PDF).
        Libère les fonds bloqués vers les bénéficiaires.
        PRÉVENTION DEADLOCKS : Verrouillage déterministe des 4 portefeuilles.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status != 'LOCKED':
                 raise ValidationError("Transaction non finalisable (Pas en status LOCKED)")

            # Récupération des Locks actifs
            locks = EscrowLock.objects.filter(offer=offer, status='LOCKED')
            if locks.count() != 2:
                 raise ValidationError("Incohérence: Nombre de locks incorrect (Attendu 2)")

            user_a1 = offer.user # Vendeur XOF
            user_a2 = offer.accepted_by # Acheteur EUR
            
            # --- IDENTIFICATION DES ACTEURS ---
            lock_a1 = locks.get(user=user_a1)
            b1_phone = offer.accepted_beneficiary_data.get('phone')
            if not b1_phone:
                 raise ValidationError("Bénéficiaire B1 manquant pour le flux XOF")
            
            b1_user = SecureEscrowService._get_user_by_phone(b1_phone)
            if not b1_user:
                 raise ValidationError(f"Utilisateur B1 introuvable avec le numéro {b1_phone}")
            
            lock_a2 = locks.get(user=user_a2)
            b2_phone = offer.beneficiary_data.get('phone')
            if not b2_phone:
                 raise ValidationError("Bénéficiaire B2 manquant pour le flux EUR")
            
            b2_user = SecureEscrowService._get_user_by_phone(b2_phone)
            if not b2_user:
                 raise ValidationError(f"Utilisateur B2 introuvable avec le numéro {b2_phone}")

            # --- VERROUILLAGE DÉTERMINISTE (Global Lock) ---
            # On récupère les IDs des usagers impliqués pour verrouiller leurs wallets dans l'ordre croissant
            # Cela empêche les deadlocks si plusieurs transactions croisées se produisent
            involved_users = sorted([user_a1.id, user_a2.id, b1_user.id, b2_user.id])
            
            # On force le verrouillage des wallets via select_for_update
            # Note: On utilise filter(user_id__in=...) pour faire une requête groupée, mais
            # pour garantir l'ordre du verrouillage DB, il est souvent plus sûr de faire des requêtes individuelles triées
            # ou d'espérer que la DB gère le row-level locking intelligemment.
            # Avec PostgreSQL, SELECT ... FOR UPDATE verrouille les lignes au fur et à mesure qu'elles sont visitées via l'index.
            # Pour être 100% sûr : boucle sur les IDs triés.
            
            wallets_map = {}
            for uid in involved_users:
                # get_or_create pour s'assurer qu'il existe
                w, _ = Wallet.objects.get_or_create(user_id=uid)
                # Verrouillage explicite
                Wallet.objects.select_for_update().get(pk=w.pk)
                wallets_map[uid] = w

            # --- EXECUTION DU SWAP ---
            
            # 1. Gestion du flux XOF (A1 -> B1)
            wallet_a1 = wallets_map[user_a1.id]
            wallet_b1 = wallets_map[b1_user.id]
            
            # --- CURRENCY SAFETY CHECK ---
            if wallet_b1.currency != lock_a1.currency:
                raise ValidationError(f"Mismatch devise B1: Attendu {lock_a1.currency}, Reçu {wallet_b1.currency}")
            
            # Débit A1
            amt_a1 = Decimal(lock_a1.amount_cents) / 100
            wallet_a1.subtract_balance(amt_a1)
            # Crédit B1
            wallet_b1.add_balance(amt_a1)
            
            # Historisation A1
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
            # Historisation B1
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

            # 2. Gestion du flux EUR (A2 -> B2)
            wallet_a2 = wallets_map[user_a2.id]
            wallet_b2 = wallets_map[b2_user.id]
            
            # --- CURRENCY SAFETY CHECK ---
            if wallet_b2.currency != lock_a2.currency:
                raise ValidationError(f"Mismatch devise B2: Attendu {lock_a2.currency}, Reçu {wallet_b2.currency}")
            
            # Débit A2
            amt_a2 = Decimal(lock_a2.amount_cents) / 100
            wallet_a2.subtract_balance(amt_a2)
            # Crédit B2
            wallet_b2.add_balance(amt_a2)
            
            # Historisation A2
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
            # Historisation B2
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
            
            # Mise à jour Offre
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

            # Notification de succès aux deux parties
            from Notifications.services import NotificationService
            
            # A1 a vendu (Débité) -> Reçoit notif de succès de la vente
            NotificationService.send(
                user=user_a1,
                title="Echange réussi !",
                body=f"Vente de {offer.amount_sell} {offer.currency_sell} terminée avec succès.",
                notification_type='transaction',
                data={'offer_id': str(offer.id)},
                channels=['push', 'email']
            )

            # A2 a acheté (Débité) -> Reçoit notif de succès de l'achat
            NotificationService.send(
                user=user_a2,
                title="Echange réussi !",
                body=f"Achat de {offer.amount_buy} {offer.currency_buy} terminé avec succès.",
                notification_type='transaction',
                data={'offer_id': str(offer.id)},
                channels=['push', 'email']
            )

    @staticmethod
    def _get_user_by_phone(phone):
        from Accounts.models import User
        import phonenumbers
        from phonenumbers import PhoneNumberFormat
        
        # Normalisation du numéro (E.164)
        try:
            # Si le numéro ne commence pas par +, on essaie de deviner ou on assume qu'il est déjà formaté
            # Pour être robuste, on parse le numéro
            parsed = phonenumbers.parse(phone, None)
            if phonenumbers.is_valid_number(parsed):
                phone = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        except Exception:
            # Si le parsing échoue, on garde le numéro tel quel (cas où c'est déjà un ID spécial ou formaté)
            pass

        try:
             return User.objects.get(full_phone_number=phone)
        except User.DoesNotExist:
             return None

    @staticmethod
    def _validate_beneficiary(beneficiary_data, expected_currency):
        """
        ✅ NOUVEAU: Valide les données du bénéficiaire et s'assure que sa devise correspond.
        """
        phone = beneficiary_data.get('phone')
        if not phone:
            raise ValidationError("Le numéro de téléphone du bénéficiaire est requis")
            
        user = SecureEscrowService._get_user_by_phone(phone)
        if not user:
            raise ValidationError(f"L'utilisateur bénéficiaire avec le numéro {phone} est introuvable")
            
        # Vérification devise via son Wallet
        wallet = Wallet.objects.filter(user=user).first()
        if not wallet or wallet.currency != expected_currency:
             raise ValidationError(
                 f"La devise du bénéficiaire ({wallet.currency if wallet else 'N/A'}) "
                 f"ne correspond pas à la devise requise pour ce flux ({expected_currency})"
             )
        
        return user

    @staticmethod
    def cancel_transaction(offer_id, reason="User Cancelled"):
        """
        Annule l'échange et libère les fonds (Rollback).
        Peut être déclenché par un timeout ou un admin.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status not in ['LOCKED', 'OPEN', 'ACCEPTED']:
                # Si déjà completed ou cancelled, on fait rien
                return

            offer.status = 'CANCELLED'
            offer.save()
            
            # Si des fonds étaient bloqués, on les libère (Rollback)
            locks = EscrowLock.objects.filter(offer=offer, status='LOCKED')
            for lock in locks:
                lock.status = 'ROLLEDBACK'
                lock.released_at = timezone.now()
                lock.save()
                # Pas de mouvement d'argent réel nécessaire car le Lock était "virtuel" 
                # (Soustrait du solde "disponible" par calcul, mais présent dans "balance_cents").
                # L'argent redevient disponible automatiquement car le lock n'est plus statut 'LOCKED'.
            
            SecureEscrowService._log_audit(
                action="OFFER_CANCELLED",
                user=offer.user,
                offer=offer,
                data={"reason": reason}
            )

    @staticmethod
    def confirm_beneficiary_participation(user, offer_id):
        """
        Permet à un bénéficiaire (B1 ou B2) de confirmer sa participation.
        Si les deux confirment, le swap est exécuté.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status != 'LOCKED':
                raise ValidationError("L'offre doit être en statut LOCKED pour confirmation par le bénéficiaire.")
                
            b1_phone = offer.accepted_beneficiary_data.get('phone')
            b2_phone = offer.beneficiary_data.get('phone')
            
            is_b1 = (user.full_phone_number == b1_phone)
            is_b2 = (user.full_phone_number == b2_phone)
            
            if not is_b1 and not is_b2:
                raise ValidationError("Vous n'êtes pas un bénéficiaire désigné pour cette offre.")
            
            # Mise à jour des flags
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
            
            # Si les deux ont confirmé, on finalise
            if offer.b1_confirmed and offer.b2_confirmed:
                SecureEscrowService.confirm_transaction(offer_id)
                logger.info("p2p_swap_auto_executed", offer_id=str(offer_id))
            
            return offer

    @staticmethod
    def dispute_transaction(offer_id, user, reason):
        """
        Signale un litige sur une transaction en cours.
        Gèle tout mouvement de fonds.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            # On peut ouvrir un litige si c'est LOCKED (fonds bloqués) ou COMPLETED (pour signaler non réception)
            if offer.status not in ['LOCKED', 'COMPLETED']:
                 raise ValidationError("Impossible d'ouvrir un litige sur cette offre")

            # Seules les parties prenantes peuvent ouvrir un litige
            if user != offer.user and user != offer.accepted_by:
                 raise ValidationError("Non autorisé")

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
        Résout un litige Admin.
        outcome: 'RELEASE_TO_BUYER', 'RELEASE_TO_SELLER', 'CANCEL_BOTH'
        """
        if not resolved_by.is_staff:
            raise ValidationError("Seul un administrateur peut résoudre un litige.")

        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            if offer.status != 'DISPUTE':
                raise ValidationError("L'offre n'est pas en litige.")

            if outcome == 'RELEASE_TO_SELLER':
                # On force la complétion de la transaction (Phase 7)
                # Note: confirm_transaction gère déjà le verrouillage déterministe
                SecureEscrowService.confirm_transaction(offer_id)
            
            elif outcome == 'CANCEL_BOTH':
                # On annule et libère les fonds (Phase Rollback)
                SecureEscrowService.cancel_transaction(offer_id, reason=f"Dispute resolved: {notes}")
            
            elif outcome == 'RELEASE_TO_BUYER':
                # Logique spécifique si on veut favoriser l'acheteur (rare dans ce flux P2P direct)
                # Pour l'instant on considère 'CANCEL_BOTH' comme le retour à l'envoyeur.
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
        """Génère un hash SHA256 pour l'intégrité du lock"""
        raw = f"{user_id}:{amount}:{offer_id}:{timezone.now().isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _log_audit(action, user, offer, data):
        """Log immuable avec chaînage hash"""
        # Récupérer le dernier hash
        last_log = AuditLog.objects.order_by('-timestamp').first()
        prev_hash = last_log.hash if last_log else "GENESIS_HASH"
        
        # Calcul nouveau hash
        raw_content = f"{prev_hash}:{action}:{user.id}:{json.dumps(data, sort_keys=True)}"
        current_hash = hashlib.sha256(raw_content.encode()).hexdigest()
        
        AuditLog.objects.create(
            action=action,
            user_id=str(user.id),
            offer_id=str(offer.id) if offer else None,
            details=data,
            previous_hash=prev_hash,
            hash=current_hash,
            amount_cents=data.get('amount_cents'), # Optionnel
            currency=data.get('currency')
        )

    # ✅ NOUVEAU: Gestion des litiges
    @staticmethod
    def initiate_dispute(offer_id, user_initiator, reason, evidence=None):
        """
        ✅ NOUVEAU: Initie un litige sur une offre.
        Permet à l'une des parties de contester une transaction.
        
        Args:
            offer_id: UUID de l'offre
            user_initiator: Utilisateur initiateur (A1 ou A2)
            reason: Raison du litige (max 500 chars)
            evidence: Dict optionnel avec screenshots/messages
        
        Returns:
            Dispute object
        """
        from .models import Dispute
        
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            # Vérifier que l'utilisateur est une des parties
            # Vérifier que l'utilisateur est une des partie
            if user_initiator not in [offer.user, offer.accepted_by]:
                raise ValidationError("Vous n'êtes pas une partie de cette offre")
            
            # Vérifier que l'offre est dans un état approprié (pas trop tôt, pas trop tard)
            if offer.status not in ['LOCKED', 'RELEASED_TO_SELLER', 'RELEASED_TO_BUYER']:
                raise ValidationError(f"Impossible de créer un litige pour une offre en statut {offer.status}")
            
            # Vérifier qu'un litige n'existe pas déjà
            existing = Dispute.objects.filter(offer=offer, status__in=['open', 'under_review']).exists()
            if existing:
                raise ValidationError("Un litige est déjà en cours pour cette offre")
            
            # Créer le litige
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
        ✅ NOUVEAU: Admin revoit et résout un litige.
        
        Args:
            dispute_id: UUID du litige
            reviewer: Admin/Staff qui revoit
            resolution: 'refund_a1', 'refund_a2', 'split'
            notes: Notes de l'admin
        
        Returns:
            Dispute object
        """
        from .models import Dispute
        
        if not reviewer.is_staff:
            raise ValidationError("Seul un administrateur peut traiter les litiges")
        
        with db_transaction.atomic():
            dispute = Dispute.objects.select_for_update().get(id=dispute_id)
            
            if dispute.status not in ['open', 'under_review']:
                raise ValidationError(f"Litige en statut {dispute.status}, impossible à résoudre")
            
            offer = dispute.offer
            
            # Implémenter la résolution
            try:
                if resolution == 'refund_a1':
                    # Rembourser A1 (user qui a créé l'offre)
                    _refund_user_for_dispute(offer.user, offer.amount_sell_cents, offer.currency_sell)
                    
                elif resolution == 'refund_a2':
                    # Rembourser A2 (user qui a accepté)
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
                raise ValidationError(f"Erreur lors de la résolution: {str(e)}")
            
            # Mettre à jour le litige
            dispute.status = 'resolved'
            dispute.resolution = resolution
            dispute.reviewed_by = reviewer
            dispute.reviewed_at = timezone.now()
            dispute.admin_notes = notes or ""
            dispute.resolved_at = timezone.now()
            dispute.save()
            
            # Mettre à jour l'offre
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
    Utilitaire pour rembourser un utilisateur suite à la résolution d'un litige.
    """
    wallet = Wallet.objects.select_for_update().get(user=user)
    
    # Créer une transaction de remboursement
    transaction_obj = Transaction.objects.create(
        wallet=wallet,
        amount_cents=amount_cents,
        currency=currency,
        transaction_type='refund',
        status='completed',
        description="Dispute resolution refund",
        reference=f"DISPUTE_{timezone.now().timestamp()}"
    )
    
    # Ajouter les fonds au portefeuille
    wallet.balance_cents = models.F('balance_cents') + amount_cents
    wallet.save(update_fields=['balance_cents'])
    
    logger.info(
        "dispute_refund_issued",
        user_id=str(user.id),
        amount=amount_cents/100,
        currency=currency,
        transaction_id=str(transaction_obj.id)
    )
