from decimal import Decimal

from django.utils.timezone import now
from rest_framework import serializers

from apps.loan_schedules.models import Loan, LoanPayment


class LoanCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a loan and generating its payment schedule.

    Accepts loan parameters such as amount, interest rate, start date,
    number of payments, and periodicity.
    """

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        initial=1000,
        help_text="Total loan amount. Must be greater than 0.",
    )
    interest_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        initial=0.1,
        help_text="Interest rate per period (e.g. 0.1 = 10%). Must be greater than 0.",
    )
    loan_start_date = serializers.DateField(
        input_formats=["%d-%m-%Y"],
        help_text="Loan start date in format DD-MM-YYYY. Cannot be in the past.",
    )
    number_of_payments = serializers.IntegerField(
        initial=4,
        help_text="Total number of scheduled payments. Must be greater than 0.",
    )
    periodicity = serializers.CharField(
        initial="1m",
        help_text="Payment periodicity in format <number><unit>, "
        "where unit is 'd' (days), 'w' (weeks), or 'm' (months). "
        "Example: 1m, 2w, 10d.",
    )

    class Meta:
        model = Loan
        fields = (
            "amount",
            "interest_rate",
            "loan_start_date",
            "number_of_payments",
            "periodicity",
        )

    def validate_periodicity(self, value: str) -> str:
        """
        Validate periodicity format.

        Expected format: <positive integer><unit>,
        where unit is one of: d, w, m.
        """
        if not value or len(value) < 2:
            raise serializers.ValidationError(
                {"periodicity": "Invalid periodicity format."}
            )

        unit = value[-1]
        if unit not in {"d", "w", "m"}:
            raise serializers.ValidationError(
                {"periodicity": "Invalid periodicity unit."}
            )

        number_part = value[:-1]
        if not number_part.isdigit():
            raise serializers.ValidationError(
                {"periodicity": "Invalid periodicity number."}
            )

        if int(number_part) <= 0:
            raise serializers.ValidationError(
                {"periodicity": "Periodicity must be > 0."}
            )

        return value

    def validate_interest_rate(self, value):
        """
        Ensure interest rate is greater than zero.
        """
        if value <= 0:
            raise serializers.ValidationError(
                {"interest_rate": "Interest rate must be > 0."}
            )
        return value

    def validate_amount(self, value):
        """
        Ensure loan amount is greater than zero.
        """
        if value <= 0:
            raise serializers.ValidationError({"amount": "Amount must be > 0."})
        return value

    def validate_number_of_payments(self, value):
        """
        Ensure number of payments is greater than zero.
        """
        if value <= 0:
            raise serializers.ValidationError(
                {"number_of_payments": "Number of payments must be > 0."}
            )
        return value

    def validate_loan_start_date(self, value):
        """
        Ensure loan start date is not in the past.
        """
        today = now().date()

        if value < today:
            raise serializers.ValidationError(
                {"loan_start_date": "Loan start date cannot be in the past."}
            )

        return value


class LoanPaymentSerializer(serializers.ModelSerializer):
    """
    Serializer for representing individual loan payments.
    """

    date = serializers.DateField(
        source="payment_date",
        read_only=True,
        help_text="Scheduled payment date.",
    )

    class Meta:
        model = LoanPayment
        fields = ("id", "date", "principal", "interest")
        help_texts = {
            "principal": "Principal amount paid in this installment.",
            "interest": "Interest amount charged for this installment.",
        }


class ReducePrincipalSerializer(serializers.Serializer):
    """
    Serializer for validating principal reduction request.
    """

    payment_id = serializers.IntegerField(
        min_value=1,
        initial=1,
        help_text="ID of loan payment to reduce",
    )
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        initial=50,
        help_text="Amount to reduce from principal",
    )


class LoanWithPaymentsSerializer(serializers.ModelSerializer):
    """
    Serializer for Loan model with nested payments.

    Returns loan main fields along with the full ordered
    list of related loan payments.
    """

    payments = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = (
            "id",
            "amount",
            "interest_rate",
            "loan_start_date",
            "periodicity",
            "payments",
        )

    def get_payments(self, obj):
        """
        Return all loan payments ordered by payment_number.
        """
        payments = obj.payments.order_by("payment_number")
        return LoanPaymentSerializer(payments, many=True).data
