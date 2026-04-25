from rest_framework import serializers
from .models import Payout, LedgerEntry, BankAccount


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ['id', 'type', 'amount_paise', 'description', 'created_at']


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = [
            'id', 'amount_paise', 'status',
            'idempotency_key', 'created_at', 'processed_at'
        ]


class CreatePayoutSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.IntegerField()

    def validate_amount_paise(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def validate_bank_account_id(self, value):
        if not BankAccount.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Invalid or inactive bank account")
        return value