from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Merchant(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def available_balance(self):
        result = LedgerEntry.objects.filter(
            merchant=self
        ).aggregate(total=Sum('amount_paise'))
        return result['total'] or 0

    def held_balance(self):
        result = Payout.objects.filter(
            merchant=self,
            status__in=['PENDING', 'PROCESSING']
        ).aggregate(total=Sum('amount_paise'))
        return result['total'] or 0


class BankAccount(models.Model):
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='bank_accounts'
    )
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.account_holder_name} - {self.account_number[-4:]}"


class LedgerEntry(models.Model):
    CREDIT = 'CREDIT'
    DEBIT = 'DEBIT'
    TYPE_CHOICES = [(CREDIT, 'Credit'), (DEBIT, 'Debit')]

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='ledger_entries'
    )
    # CREDITS are positive (+500000)
    # DEBITS are negative (-200000)
    # SUM(amount_paise) = balance always
    amount_paise = models.BigIntegerField()
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    description = models.CharField(max_length=500)
    payout = models.ForeignKey(
        'Payout',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='ledger_entries'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} {self.amount_paise} for {self.merchant}"


class Payout(models.Model):
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PROCESSING, 'Processing'),
        (COMPLETED, 'Completed'),
        (FAILED, 'Failed'),
    ]

    VALID_TRANSITIONS = {
        PENDING: [PROCESSING],
        PROCESSING: [COMPLETED, FAILED],
        COMPLETED: [],
        FAILED: [],
    }

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.PROTECT,
        related_name='payouts'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT
    )
    amount_paise = models.BigIntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING
    )
    idempotency_key = models.CharField(max_length=255)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('merchant', 'idempotency_key')]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['merchant', 'status']),
        ]

    def transition_to(self, new_status):
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {self.status} → {new_status}"
            )
        self.status = new_status
        if new_status in [self.COMPLETED, self.FAILED]:
            self.processed_at = timezone.now()
        self.save()

    def __str__(self):
        return f"Payout #{self.id} - {self.status}"


class IdempotencyKey(models.Model):
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE
    )
    key = models.CharField(max_length=255)
    response_body = models.JSONField()
    response_status = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('merchant', 'key')]

    def __str__(self):
        return f"{self.merchant} - {self.key}"