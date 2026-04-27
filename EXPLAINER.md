# EXPLAINER.md — Playto Payout Engine

---

## 1. The Ledger

**Balance calculation query:**

```python
def available_balance(self):
    result = LedgerEntry.objects.filter(
        merchant=self
    ).aggregate(total=Sum('amount_paise'))
    return result['total'] or 0
```

This translates to a single SQL query:
```sql
SELECT SUM(amount_paise) FROM payouts_ledgerentry WHERE merchant_id = %s;
```

**Why this model?**

Credits are stored as positive integers, debits as negative integers. `SUM(amount_paise)` is always the true balance — no separate credit/debit columns to keep in sync, no Python arithmetic on fetched rows. The invariant `SUM(credits) - SUM(debits) = balance` holds automatically because it is the same column.

Every money movement — customer payment, payout initiation, refund on failure — is an immutable ledger row. Nothing is ever updated or deleted. The balance is always derived, never stored. This means the full audit trail is free.

Amounts are stored as `BigIntegerField` in paise. No floats, no decimals, no rounding errors. `100000 paise = ₹1000.00`, always exact.

---

## 2. The Lock

**Exact code that prevents concurrent overdraw:**

```python
with transaction.atomic():
    # Acquires a row-level exclusive lock on the merchant row.
    # Any other transaction attempting select_for_update() on the
    # same merchant will block here until this transaction commits.
    merchant_locked = Merchant.objects.select_for_update().get(
        id=merchant.id
    )

    # Balance is calculated AFTER the lock is acquired.
    # No other transaction can insert a ledger entry for this
    # merchant until we release the lock.
    balance = LedgerEntry.objects.filter(
        merchant=merchant_locked
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    if balance < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=400)

    # Create payout + debit ledger entry inside the same transaction.
    # Lock is released only when this block exits.
    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

**What database primitive it relies on:**

`SELECT FOR UPDATE` — a PostgreSQL row-level exclusive lock. When Thread A calls `select_for_update()` on merchant row 1, PostgreSQL places an exclusive lock. Thread B attempting the same query blocks at the database level until Thread A's `transaction.atomic()` block commits or rolls back. This is not a Python-level lock — it survives across threads, processes, and even multiple Gunicorn workers.

The balance check and the debit write happen inside the same atomic transaction. There is no window between "check balance" and "write debit" where another transaction can sneak in.

---

## 3. The Idempotency

**How the system knows it has seen a key before:**

```python
existing = IdempotencyKey.objects.filter(
    merchant=merchant,
    key=idempotency_key,
    created_at__gte=timezone.now() - timedelta(hours=24)
).first()

if existing:
    return Response(existing.response_body, status=existing.response_status)
```

The `IdempotencyKey` table stores the merchant, the key string, the full JSON response body, and the HTTP status code. On every POST to `/api/v1/payouts`, we look up the key before doing any work. If found and within 24 hours, we return the stored response byte-for-byte. No new payout is created.

Keys are scoped per merchant via a `unique_together = [('merchant', 'key')]` constraint. The same key string from two different merchants is treated as two different keys.

**What happens if the first request is in-flight when the second arrives:**

The `IdempotencyKey` row is created inside the `transaction.atomic()` block, after the payout and ledger entry are written but before the transaction commits. If a second request arrives before the first transaction commits, it will not find the key in the database and will attempt to proceed. It will then hit the `unique_together` constraint on `IdempotencyKey` and raise an `IntegrityError`, which rolls back the entire transaction and returns a 500. This is an acceptable edge case — the client retrying after a genuine timeout will succeed on the next retry once the first transaction has committed and the key is visible.

A more robust solution would be to pre-insert the key with a `PENDING` status before processing, then update it on completion. That would serialize the in-flight race at the key lookup step.

---

## 4. The State Machine

**Where illegal transitions are blocked:**

```python
VALID_TRANSITIONS = {
    PENDING: [PROCESSING],
    PROCESSING: [COMPLETED, FAILED],
    COMPLETED: [],   # terminal — no exits
    FAILED: [],      # terminal — no exits
}

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
```

`COMPLETED` and `FAILED` map to empty lists. Any call to `transition_to()` from either terminal state raises `ValueError` before touching the database. The `tasks.py` worker always goes through `transition_to()` — it never sets `payout.status` directly. So `failed → completed`, `completed → pending`, and any other illegal move is structurally impossible through the normal code path.

The fund return on failure is atomic with the state transition:

```python
with transaction.atomic():
    payout.transition_to(Payout.FAILED)        # state change
    LedgerEntry.objects.create(                 # fund return
        amount_paise=+payout.amount_paise, ...
    )
```

Both writes succeed or both are rolled back. The balance is never left in a deducted state with a non-FAILED payout, and a FAILED payout never exists without its corresponding credit entry.

---

## 5. The AI Audit

**What AI gave me — wrong aggregation outside the lock:**

When I first asked an AI assistant to write the balance check, it generated this pattern:

```python
# AI-generated — DO NOT USE
def post(self, request):
    merchant = Merchant.objects.get(id=merchant_id)
    balance = merchant.available_balance()   # fetched here, outside any lock

    with transaction.atomic():
        if balance < amount_paise:           # stale read — race condition
            return Response({'error': 'Insufficient balance'}, status=400)
        Payout.objects.create(...)
        LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

**What I caught:**

The balance is fetched before `transaction.atomic()` and before any lock. Two concurrent requests both read the same balance (say, 10000 paise), both pass the `if balance < amount_paise` check, and both proceed to create a payout and debit the ledger. The merchant ends up with a negative balance.

This is the classic check-then-act race condition. The AI correctly identified that a check was needed but placed it in the wrong position — outside the critical section.

**What I replaced it with:**

```python
with transaction.atomic():
    merchant_locked = Merchant.objects.select_for_update().get(id=merchant.id)

    # Balance recalculated INSIDE the lock — guaranteed fresh
    balance = LedgerEntry.objects.filter(
        merchant=merchant_locked
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    if balance < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=400)

    Payout.objects.create(...)
    LedgerEntry.objects.create(amount_paise=-amount_paise, ...)
```

The lock is acquired first. The balance is calculated after the lock is held. No other transaction can modify ledger entries for this merchant until the atomic block exits. The concurrency test — two simultaneous 60-rupee requests against a 100-rupee balance — confirms exactly one succeeds.