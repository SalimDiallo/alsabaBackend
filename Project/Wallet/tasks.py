from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Transaction
from .Services.flutterwave_service import flutterwave_service
import structlog

logger = structlog.get_logger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60  # 1 minute between retries
)
def reconcile_transactions(self):
    """
    CRITICAL: Checks 'pending' or 'processing' transactions older than 5-10 min.
    Reconciles with Flutterwave to avoid loss of funds.
    Exponential retry in case of error.
    """
    # REDUCED FROM 30 min TO 10 min FOR FAST DETECTION
    threshold = timezone.now() - timedelta(minutes=10)
    
    # Transactions to verify
    pending_txs = Transaction.objects.filter(
        status__in=['pending', 'processing'],
        created_at__lt=threshold
    ).select_related('wallet__user') # Optimization
    
    count = 0
    
    for tx in pending_txs:
        count += 1
        logger.info("reconciling_transaction", transaction_id=str(tx.id), ref=tx.flutterwave_reference)
        
        try:
            # 1. If no Flutterwave reference, it's likely an early failure or a bug
            if not tx.flutterwave_reference:
                # If > 24h, mark as failed
                if tx.created_at < (timezone.now() - timedelta(hours=24)):
                    tx.mark_failed(error_message="Timeout: No Flutterwave reference generated")
                continue

            # 2. Flutterwave Verify API call
            # Note: flutterwave_service.verify_transaction must be implemented or use the existing one
            # We assume here that we can verify by ID or REF.
            
            # Appel direct
            # Use numeric transaction ID if available (more reliable), otherwise reference
            flw_id = tx.flutterwave_transaction_id
            
            # Call with payment_method to avoid mapping errors
            try:
                verification = flutterwave_service.verify_transaction(
                    transaction_id=flw_id if flw_id else tx.flutterwave_reference,
                    payment_method=tx.payment_method
                )
            except Exception as e:
                # EXPONENTIAL RETRY if network error
                logger.warning("reconciliation_api_error_retry", tx_id=str(tx.id), error=str(e), retry_count=self.request.retries)
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
            
            if not verification['success']:
                # If API fails, retry after delay
                logger.warning("reconciliation_api_error", tx_id=str(tx.id), error=verification.get('error'))
                continue
                
            data = verification.get('data', {})
            status = data.get('status')
            
            # 3. Update according to status
            if status == "successful":
                # Rare case: Webhook missed but transaction successful
                logger.info("reconciliation_success_found", tx_id=str(tx.id))
                tx.mark_completed()
                
            elif status == "failed":
                logger.info("reconciliation_failure_found", tx_id=str(tx.id))
                # IMPORTANT: If it was a withdrawal (funds debited), it must be refunded!
                if tx.transaction_type == 'withdrawal' and tx.balance_adjusted:
                    # Refund logic included in mark_failed if improved,
                    # or done manually here like in the webhook.
                    # To be sure, we use the webhook logic:
                    from decimal import Decimal
                    total_to_refund = (Decimal(tx.amount_cents) + Decimal(tx.fee_cents)) / 100
                    tx.wallet.add_balance(total_to_refund)
                    tx.balance_adjusted = False
                    logger.info("transaction_refund_issued", tx_id=str(tx.id), amount=total_to_refund)
                    
                tx.mark_failed(error_message=f"Reconciliation: Found status {status}")
                
            # Other statuses (pending) let them continue
            
        except Exception:
            logger.exception("reconciliation_error", tx_id=str(tx.id))

    return f"Reconciled {count} transactions."
