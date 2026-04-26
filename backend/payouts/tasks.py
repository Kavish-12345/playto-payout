import random
from django.db import transaction
from django.utils import timezone
from datetime import timedelta


def process_payout(payout_id):
    from .models import Payout, LedgerEntry

    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        return

    # Handle both PENDING and PROCESSING (retries)
    if payout.status not in [Payout.PENDING, Payout.PROCESSING]:
        return

    # If PENDING move to PROCESSING
    if payout.status == Payout.PENDING:
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
        # 10% hang - do nothing
        # retry_stuck_payouts will pick it up again
        pass


def retry_stuck_payouts():
    from .models import Payout, LedgerEntry
    from django_q.tasks import async_task

    cutoff = timezone.now() - timedelta(seconds=30)

    # Retry stuck payouts under max attempts
    stuck = Payout.objects.filter(
        status=Payout.PROCESSING,
        updated_at__lt=cutoff,
        attempts__lt=3
    )
    for payout in stuck:
        async_task('payouts.tasks.process_payout', payout.id)

    # Force fail payouts over max attempts
    over_limit = Payout.objects.filter(
        status=Payout.PROCESSING,
        updated_at__lt=cutoff,
        attempts__gte=3
    )
    for payout in over_limit:
        with transaction.atomic():
            payout.transition_to(Payout.FAILED)
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                amount_paise=+payout.amount_paise,
                type=LedgerEntry.CREDIT,
                description=f"Refund for stuck payout #{payout.id}",
                payout=payout
            )