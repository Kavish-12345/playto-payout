import random
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from datetime import timedelta


@shared_task(bind=True, max_retries=3)
def process_payout(self, payout_id):
    from .models import Payout, LedgerEntry

    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        return

    # Only process PENDING payouts
    if payout.status != Payout.PENDING:
        return

    # Move to PROCESSING
    payout.transition_to(Payout.PROCESSING)
    payout.attempts += 1
    payout.save()

    # Simulate bank response
    outcome = random.random()

    if outcome < 0.70:
        # 70% success
        payout.transition_to(Payout.COMPLETED)

    elif outcome < 0.90:
        # 20% failure - return funds atomically
        with transaction.atomic():
            payout.transition_to(Payout.FAILED)
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                amount_paise=+payout.amount_paise,
                type=LedgerEntry.CREDIT,
                description=f"Refund for failed payout #{payout.id}",
                payout=payout
            )
    else:
        # 10% hang - do nothing, retry handles it
        pass


@shared_task
def retry_stuck_payouts():
    from .models import Payout

    cutoff = timezone.now() - timedelta(seconds=30)

    stuck = Payout.objects.filter(
        status=Payout.PROCESSING,
        updated_at__lt=cutoff,
        attempts__lt=3
    )

    for payout in stuck:
        process_payout.delay(payout.id)

    # Force fail payouts that exceeded max attempts
    failed = Payout.objects.filter(
        status=Payout.PROCESSING,
        updated_at__lt=cutoff,
        attempts__gte=3
    )

    for payout in failed:
        with transaction.atomic():
            payout.transition_to(Payout.FAILED)
            from .models import LedgerEntry
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                amount_paise=+payout.amount_paise,
                type=LedgerEntry.CREDIT,
                description=f"Refund for stuck payout #{payout.id}",
                payout=payout
            )