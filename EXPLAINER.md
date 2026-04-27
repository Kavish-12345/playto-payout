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

Credits are stored as positive integers, debits as negative integers. `SUM(amount_paise)` is always the true balance — no separate credit/debit columns to keep in sync, no Python arithmetic on fetched rows leading to negligible chances of balance calculations going wrong in the ledger while the credits and debits happen. Every transaction is immutable → perfect audit trail.
Every money movement — customer payment, payout initiation, refund on failure — is an immutable ledger row. Nothing is ever updated or deleted. The balance is always derived, never stored. This means the full audit trail is free. When someone asks for a merchant's balance the MerchantBalanceView simply pulls that merchant calculates balance from ledger entries and returns latest transactions, no complexity faced. (Double-entry accounting principles (simplified))

Amounts are stored as `BigIntegerField` in paise. No floats, no decimals, no rounding errors.

---

## 2. Concurrency Control via Row-Level Locking

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

Inside transaction.atomic() with select_for_update() - It basically locks that particular merchant row and no other transaction attempting to acquire the same lock can proceed until the atomic transaction steps are complete. This prevents two payout requests from reading the same balance at the same time and overspending.

Once locked, you recompute the balance directly from the ledger (source of truth). If funds are insufficient, you fail safely.
If sufficient, you:
1) Create a payout record (status = PENDING)
2) Immediately create a ledger debit entry (this “holds” the money)

So the money is deducted before actual processing happens. This is how systems ensure consistency.

Then you store the idempotency response so retries are safe.

After the transaction completes, an async task is triggered using Django Q. This is the key — don't actually process the payout inside the request, just queue it.

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

**What this implementation does:**

The idempotency key is written inside the `transaction.atomic()` block and becomes visible only after the transaction commits.
If two requests with the same key arrive concurrently, the second request may not see the key and will attempt to proceed. It will then hit the `(merchant, key)` unique constraint, raising an `IntegrityError` and resulting in a 500 response. This approach still guarantees correctness — no duplicate payouts are created — because the database enforces uniqueness.
However, returning a 500 for a valid retry is not ideal for a production system, as the client cannot distinguish between a failure and an in-progress request. A more robust design would pre-insert the idempotency key with a `PENDING` state before executing business logic. This would serialize concurrent requests at the key lookup stage and allow deterministic responses for retries.
For the scope of this challenge, the current approach ensures strong consistency and correctness, while keeping the implementation simple.
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

The balance is fetched before entering `transaction.atomic()` and before acquiring any lock. This means multiple concurrent requests can read the balance before any synchronization is applied. Each request may observe the same pre-debit state (e.g. 10000 paise), pass the `if balance < amount_paise` check, and proceed to create a payout and debit the ledger. This leads to overspending and can result in a negative balance, violating the system’s core invariant. This is a classic check-then-act race condition — the decision is made on a value that is not protected from concurrent modification. The issue is not just that the check happens "outside the critical section", but that the read and write are not performed under the same lock, allowing concurrent transactions to interleave. The correct approach is to acquire the lock first, then compute the balance, ensuring the decision is based on a consistent and isolated state.

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
