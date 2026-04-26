from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Merchant, Payout, LedgerEntry, IdempotencyKey, BankAccount
from .serializers import (
    CreatePayoutSerializer,
    PayoutSerializer,
    LedgerEntrySerializer
)


class MerchantBalanceView(APIView):
    """
    GET /api/v1/merchants/<merchant_id>/balance
    Returns available balance, held balance, recent transactions
    """
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response(
                {'error': 'Merchant not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        ledger = merchant.ledger_entries.order_by('-created_at')[:20]

        return Response({
            'merchant_id': merchant.id,
            'merchant_name': merchant.name,
            'available_balance_paise': merchant.available_balance(),
            'held_balance_paise': merchant.held_balance(),
            'recent_transactions': LedgerEntrySerializer(ledger, many=True).data
        })


class PayoutListCreateView(APIView):
    """
    POST /api/v1/payouts
    Creates a payout with locking + idempotency
    """
    def post(self, request):
        # Step 1 - get merchant (hardcoded to 1 for now, frontend will pass it)
        merchant_id = request.data.get('merchant_id')
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response(
                {'error': 'Merchant not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Step 2 - check idempotency key
        idempotency_key = request.headers.get('Idempotency-Key')
        if not idempotency_key:
            return Response(
                {'error': 'Idempotency-Key header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if we have seen this key before
        existing = IdempotencyKey.objects.filter(
            merchant=merchant,
            key=idempotency_key,
            # Keys expire after 24 hours
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).first()

        if existing:
            # Return exact same response as first request
            return Response(
                existing.response_body,
                status=existing.response_status
            )

        # Step 3 - validate request body
        serializer = CreatePayoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        amount_paise = serializer.validated_data['amount_paise']
        bank_account_id = serializer.validated_data['bank_account_id']

        # Step 4 - the critical section
        # select_for_update() locks the merchant row
        # No other transaction can read or modify this row
        # until our transaction completes
        try:
            with transaction.atomic():
                # LOCK the merchant row at database level
                # Thread B will wait here if Thread A is processing
                merchant_locked = Merchant.objects.select_for_update().get(
                    id=merchant.id
                )

                # Calculate balance AFTER acquiring lock
                # This is safe now — no other thread can change it
                balance = LedgerEntry.objects.filter(
                    merchant=merchant_locked
                ).aggregate(total=Sum('amount_paise'))['total'] or 0

                # Check if sufficient balance
                if balance < amount_paise:
                    return Response(
                        {
                            'error': 'Insufficient balance',
                            'available_paise': balance,
                            'requested_paise': amount_paise
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                bank_account = BankAccount.objects.get(id=bank_account_id)

                # Create the payout record
                payout = Payout.objects.create(
                    merchant=merchant_locked,
                    bank_account=bank_account,
                    amount_paise=amount_paise,
                    status=Payout.PENDING,
                    idempotency_key=idempotency_key
                )

                # Deduct from ledger immediately (holds the funds)
                # Negative amount = debit
                LedgerEntry.objects.create(
                    merchant=merchant_locked,
                    amount_paise=-amount_paise,
                    type=LedgerEntry.DEBIT,
                    description=f"Payout #{payout.id} initiated",
                    payout=payout
                )

                # Build response
                response_data = PayoutSerializer(payout).data

                # Save idempotency key with response
                # Future duplicate requests return this exact response
                IdempotencyKey.objects.create(
                    merchant=merchant_locked,
                    key=idempotency_key,
                    response_body=response_data,
                    response_status=201
                )

            # Queue the payout for processing
            # Import here to avoid circular imports
            from django_q.tasks import async_task
            async_task('payouts.tasks.process_payout', payout.id)

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        merchant_id = request.query_params.get('merchant_id')
        if not merchant_id:
            return Response(
                {'error': 'merchant_id query param required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        payouts = Payout.objects.filter(
            merchant_id=merchant_id
        ).order_by('-created_at')

        return Response(PayoutSerializer(payouts, many=True).data)


class MerchantListView(APIView):
    """
    GET /api/v1/merchants
    Returns list of all merchants
    """
    def get(self, request):
        merchants = Merchant.objects.all()
        data = []
        for m in merchants:
            data.append({
                'id': m.id,
                'name': m.name,
                'email': m.email,
                'available_balance_paise': m.available_balance(),
                'held_balance_paise': m.held_balance(),
            })
        return Response(data)