from django.core.management.base import BaseCommand
from payouts.models import Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey


class Command(BaseCommand):
    help = 'Seed database with test merchants'

    def handle(self, *args, **kwargs):
        # Delete in correct order - children before parents
        IdempotencyKey.objects.all().delete()
        LedgerEntry.objects.all().delete()
        Payout.objects.all().delete()
        BankAccount.objects.all().delete()
        Merchant.objects.all().delete()

        # Merchant 1
        acme = Merchant.objects.create(
            name="Acme Agency",
            email="acme@test.com"
        )
        BankAccount.objects.create(
            merchant=acme,
            account_number="1234567890",
            ifsc_code="HDFC0001234",
            account_holder_name="Acme Agency"
        )
        LedgerEntry.objects.bulk_create([
            LedgerEntry(merchant=acme, amount_paise=500000,
                type='CREDIT', description="Payment from Client A"),
            LedgerEntry(merchant=acme, amount_paise=300000,
                type='CREDIT', description="Payment from Client B"),
            LedgerEntry(merchant=acme, amount_paise=1000000,
                type='CREDIT', description="Payment from Client C"),
        ])

        # Merchant 2
        studio = Merchant.objects.create(
            name="Studio X",
            email="studio@test.com"
        )
        BankAccount.objects.create(
            merchant=studio,
            account_number="9876543210",
            ifsc_code="ICIC0005678",
            account_holder_name="Studio X"
        )
        LedgerEntry.objects.bulk_create([
            LedgerEntry(merchant=studio, amount_paise=750000,
                type='CREDIT', description="Payment from Client D"),
            LedgerEntry(merchant=studio, amount_paise=250000,
                type='CREDIT', description="Payment from Client E"),
        ])

        self.stdout.write(self.style.SUCCESS(
            f'Done!\n'
            f'Acme Agency balance: ₹{acme.available_balance()/100}\n'
            f'Studio X balance: ₹{studio.available_balance()/100}'
        ))