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
        if user.kyc_status != 'verified':
            raise ValidationError("KYC requis pour créer une offre.")

        wallet = WalletService.get_or_create_wallet(user)
        
        # Vérification simple du solde (pas de lock ici, le lock se fait au moment du Match)
        # Mais on empêche de créer une offre si on est à sec pour éviter le spam
        amount_sell_cents = int(Decimal(str(amount_sell)) * 100)
        
        # Le solde disponible doit prendre en compte les autres locks actifs !
        # Dispo = Solde Réel - Somme(Locks Actifs)
        locked_amount = EscrowLock.objects.filter(
            user=user, 
            currency=currency_sell, 
            status='LOCKED'
        ).aggregate(sum=models.Sum('amount_cents'))['sum'] or 0
        
        real_balance = wallet.balance_cents
        available_balance = real_balance - locked_amount
        
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
        try:
            offer = Offer.objects.select_for_update().get(id=offer_id)
        except Offer.DoesNotExist:
            raise ValidationError("Offre introuvable")

        if offer.status != 'OPEN':
            raise ValidationError(f"Offre non disponible (Statut: {offer.status})")
            
        if offer.user == user_accepter:
            raise ValidationError("Impossible d'accepter sa propre offre")

        if user_accepter.kyc_status != 'verified':
            raise ValidationError("KYC requis pour accepter une offre.")
            
        # A1 = offer.user (Vendeur initial)
        # A2 = user_accepter (Acheteur)
        
        user_a1 = offer.user
        user_a2 = user_accepter
        
        # Montants à bloquer
        amount_lock_a1 = offer.amount_sell_cents # XOF
        amount_lock_a2 = offer.amount_buy_cents  # EUR
        
        # Transaction Atomique Globale
        with db_transaction.atomic():
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
            offer.status = 'LOCKED'
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
        """
        # Note: Pour cet exemple, on suppose que c'est déclenché automatiquement ou par une confirmation mutuelle.
        # Dans un vrai scénario, il faudrait passer user_id du déclencheur.
        
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
            
            # --- EXECUTION DU SWAP ---
            # Modèle:
            # A1 (XOF) -> Paye B1 (A2's friend, XOF)
            # A2 (EUR) -> Paye B2 (A1's friend, EUR)
            
            # 1. Gestion du flux XOF (A1 -> B1)
            lock_a1 = locks.get(user=user_a1)
            b1_phone = offer.accepted_beneficiary_data.get('phone')
            if not b1_phone:
                 # Fallback: Si pas de B1 précisé, on crédite A2 ? 
                 # Le User dit "A2 precise son ami B1". Si absent, erreur ou fallback A2.
                 raise ValidationError("Bénéficiaire B1 manquant pour le flux XOF")
            
            # Trouver Wallet B1
            b1_user = SecureEscrowService._get_user_by_phone(b1_phone)
            if not b1_user:
                 raise ValidationError(f"Utilisateur B1 introuvable avec le numéro {b1_phone}")
            
            wallet_b1 = WalletService.get_or_create_wallet(b1_user)
            
            # Débit Réel A1 (Soustraction du Lock)
            wallet_a1 = WalletService.get_or_create_wallet(user_a1)
            wallet_a1.subtract_balance(Decimal(lock_a1.amount_cents) / 100)
            
            # Crédit Réel B1
            wallet_b1.add_balance(Decimal(lock_a1.amount_cents) / 100)
            
            lock_a1.status = 'RELEASED'
            lock_a1.released_at = timezone.now()
            lock_a1.save()

            # 2. Gestion du flux EUR (A2 -> B2)
            lock_a2 = locks.get(user=user_a2)
            b2_phone = offer.beneficiary_data.get('phone')
            if not b2_phone:
                 raise ValidationError("Bénéficiaire B2 manquant pour le flux EUR")
            
            # Trouver Wallet B2
            b2_user = SecureEscrowService._get_user_by_phone(b2_phone)
            if not b2_user:
                 raise ValidationError(f"Utilisateur B2 introuvable avec le numéro {b2_phone}")
            
            wallet_b2 = WalletService.get_or_create_wallet(b2_user)
            
            # Débit Réel A2
            wallet_a2 = WalletService.get_or_create_wallet(user_a2)
            wallet_a2.subtract_balance(Decimal(lock_a2.amount_cents) / 100)
            
            # Crédit Réel B2
            wallet_b2.add_balance(Decimal(lock_a2.amount_cents) / 100)
            
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

    @staticmethod
    def _get_user_by_phone(phone):
        from Accounts.models import User
        # Essayer de trouver un match exact ou partiel
        # Supposons que phone est clean
        try:
             return User.objects.get(full_phone_number=phone)
        except User.DoesNotExist:
             return None

    @staticmethod
    def cancel_transaction(offer_id, reason="User Cancelled"):
        """
        Annule l'échange et libère les fonds (Rollback).
        Peut être déclenché par un timeout ou un admin.
        """
        with db_transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer_id)
            
            if offer.status not in ['LOCKED', 'OPEN']:
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
