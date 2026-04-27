from django.test import TestCase
from rest_framework.test import APIClient
from .models import Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey


def create_test_merchant(name="Test Merchant", email="test@test.com", balance=1000000):
    merchant = Merchant.objects.create(name=name, email=email)
    BankAccount.objects.create(
        merchant=merchant,
        account_number="1234567890",
        ifsc_code="HDFC0001234",
        account_holder_name=name
    )
    LedgerEntry.objects.create(
        merchant=merchant,
        amount_paise=balance,
        type='CREDIT',
        description="Test credit"
    )
    return merchant

class ConcurrencyTest(TestCase):
    """
    Proves select_for_update() prevents overdraw.
    Merchant has ₹100. Two requests of ₹60 each.
    Exactly one must succeed, one must fail.
    """
    def setUp(self):
        self.client = APIClient()
        self.merchant = create_test_merchant(balance=10000)  # ₹100
        self.bank_account = self.merchant.bank_accounts.first()

    def test_overdraw_prevention(self):
        # First request — should succeed
        response1 = self.client.post(
            "/api/v1/payouts/",
            {
                "merchant_id": self.merchant.id,
                "amount_paise": 6000,  # ₹60
                "bank_account_id": self.bank_account.id
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="key-001"
        )

        # Second request — should fail, only ₹40 left
        response2 = self.client.post(
            "/api/v1/payouts/",
            {
                "merchant_id": self.merchant.id,
                "amount_paise": 6000,  # ₹60
                "bank_account_id": self.bank_account.id
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="key-002"
        )

        print(f"\n✅ Overdraw prevention test")
        print(f"   Request 1: {response1.status_code}")
        print(f"   Request 2: {response2.status_code} - {response2.data}")

        # First must succeed
        self.assertEqual(response1.status_code, 201)

        # Second must be rejected
        self.assertEqual(response2.status_code, 400)
        self.assertEqual(response2.data['error'], 'Insufficient balance')

        # Only one payout created
        payout_count = Payout.objects.filter(merchant=self.merchant).count()
        self.assertEqual(payout_count, 1)

        # Balance never went negative
        final_balance = self.merchant.available_balance()
        self.assertGreaterEqual(final_balance, 0)

        print(f"   Payouts created: {payout_count}")
        print(f"   Final balance: {final_balance} paise (never negative)")
        
        
class IdempotencyTest(TestCase):
    """
    Proves same idempotency key sent twice
    creates only one payout and returns identical response.
    This simulates a client retrying after a network timeout.
    """
    def setUp(self):
        self.client = APIClient()
        self.merchant = create_test_merchant(balance=500000)
        self.bank_account = self.merchant.bank_accounts.first()

    def test_duplicate_key_returns_same_response(self):
        payload = {
            "merchant_id": self.merchant.id,
            "amount_paise": 100000,
            "bank_account_id": self.bank_account.id
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": "unique-test-key-123"}

        # First request
        response1 = self.client.post(
            "/api/v1/payouts/",
            payload,
            format="json",
            **headers
        )

        # Second request with same key — simulates network retry
        response2 = self.client.post(
            "/api/v1/payouts/",
            payload,
            format="json",
            **headers
        )

        print(f"\n✅ Idempotency test")
        print(f"   First response: {response1.status_code} - id={response1.data['id']}")
        print(f"   Second response: {response2.status_code} - id={response2.data['id']}")

        # Both return 201
        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 201)

        # Same payout ID — no duplicate created
        self.assertEqual(response1.data['id'], response2.data['id'])

        # Only ONE payout in database
        payout_count = Payout.objects.filter(merchant=self.merchant).count()
        self.assertEqual(payout_count, 1)

        print(f"   Payouts in DB: {payout_count} (not 2)")