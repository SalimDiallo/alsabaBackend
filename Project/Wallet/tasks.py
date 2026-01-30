from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Transaction
from .Services.wallet_service import WalletService
from .Services.flutterwave_service import flutterwave_service
import structlog

logger = structlog.get_logger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60  # 1 minute entre tentatives
)
def reconcile_transactions(self):
    """
    ✅ CRITIQUE: Vérifie les transactions 'pending' ou 'processing' vieilles de 5-10 min.
    Réconcilie avec Flutterwave pour éviter les pertes de fonds.
    Retry exponential en cas d'erreur.
    """
    # ⚠️ RÉDUIT DE 30 min À 10 min POUR DÉTECTION RAPIDE
    threshold = timezone.now() - timedelta(minutes=10)
    
    # Transactions à vérifier
    pending_txs = Transaction.objects.filter(
        status__in=['pending', 'processing'],
        created_at__lt=threshold
    ).select_related('wallet__user') # Optimisation
    
    count = 0
    
    for tx in pending_txs:
        count += 1
        logger.info("reconciling_transaction", transaction_id=str(tx.id), ref=tx.flutterwave_reference)
        
        try:
            # 1. Si pas de référence Flutterwave, c'est probablement un échec précoce ou un bug
            if not tx.flutterwave_reference:
                # Si > 24h, on marque failed
                if tx.created_at < (timezone.now() - timedelta(hours=24)):
                    tx.mark_failed(error_message="Timeout: Aucune référence Flutterwave générée")
                continue

            # 2. Appel API Flutterwave Verify
            # Note: flutterwave_service.verify_transaction doit être implémenté ou on utilise l'existant
            # On suppose ici qu'on peut vérifier par ID ou REF.
            
            # Appel direct
            # Utilisation de l'ID de transaction numérique si dispo (plus fiable), sinon référence
            flw_id = tx.flutterwave_transaction_id
            
            # Appel avec payment_method pour éviter les erreurs de mapping
            try:
                verification = flutterwave_service.verify_transaction(
                    transaction_id=flw_id if flw_id else tx.flutterwave_reference,
                    payment_method=tx.payment_method
                )
            except Exception as e:
                # ✅ RETRY EXPONENTIAL si erreur réseau
                logger.warning("reconciliation_api_error_retry", tx_id=str(tx.id), error=str(e), retry_count=self.request.retries)
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
            
            if not verification['success']:
                # Si l'API échoue, retry après délai
                logger.warning("reconciliation_api_error", tx_id=str(tx.id), error=verification.get('error'))
                continue
                
            data = verification.get('data', {})
            status = data.get('status')
            
            # 3. Mise à jour selon statut
            if status == "successful":
                # Cas rare : Webhook manqué mais transaction réussie
                logger.info("reconciliation_success_found", tx_id=str(tx.id))
                tx.mark_completed()
                
            elif status == "failed":
                logger.info("reconciliation_failure_found", tx_id=str(tx.id))
                # IMPORTANT: Si c'était un retrait (fonds débités), il faut rembourser !
                if tx.transaction_type == 'withdrawal' and tx.balance_adjusted:
                    # Logique de remboursement incluse dans mark_failed si on l'améliore, 
                    # ou on le fait manuellement ici comme dans le webhook.
                    # Pour être sûr, on utilise la logique du webhook:
                    from decimal import Decimal
                    total_to_refund = (Decimal(tx.amount_cents) + Decimal(tx.fee_cents)) / 100
                    tx.wallet.add_balance(total_to_refund)
                    tx.balance_adjusted = False
                    logger.info("transaction_refund_issued", tx_id=str(tx.id), amount=total_to_refund)
                    
                tx.mark_failed(error_message=f"Reconciliation: Found status {status}")
                
            # Les autres statuts (pending) on laisse courir
            
        except Exception as e:
            logger.exception("reconciliation_error", tx_id=str(tx.id))

    return f"Reconciled {count} transactions."
