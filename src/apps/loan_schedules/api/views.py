from django.db import transaction
from rest_framework.generics import (
    CreateAPIView,
    ListAPIView,
    UpdateAPIView,
    get_object_or_404,
)
from rest_framework.response import Response

from apps.loan_schedules.models import Loan, LoanPayment

from .serializers import (
    LoanCreateSerializer,
    LoanPaymentSerializer,
    LoanWithPaymentsSerializer,
    ReducePrincipalSerializer,
)
from .services import DecliningBalancePrincipalReducer, generate_schedule


class LoanCreateScheduleView(CreateAPIView):
    """
    API view for creating a loan and generating its repayment schedule.
    """

    serializer_class = LoanCreateSerializer
    queryset = Loan.objects.none()

    def create(self, request, *args, **kwargs):
        """
        Create loan and its payment schedule atomically.

        Returns a list of generated loan payments with principal
        and interest breakdown per payment.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            loan = Loan.objects.create(**serializer.validated_data)

            payments = generate_schedule(
                amount=loan.amount,
                start_date=loan.loan_start_date,
                number_of_payments=loan.number_of_payments,
                periodicity=loan.periodicity,
                interest_rate=loan.interest_rate,
            )

            LoanPayment.objects.bulk_create(
                [
                    LoanPayment(
                        loan=loan,
                        payment_number=payment["payment_number"],
                        payment_date=payment["date"],
                        principal=payment["principal"],
                        interest=payment["interest"],
                    )
                    for payment in payments
                ]
            )

        created_payments = LoanPayment.objects.filter(loan=loan).order_by(
            "payment_number"
        )

        return Response(LoanPaymentSerializer(created_payments, many=True).data)


class ReducePrincipalView(UpdateAPIView):
    """
    PATCH endpoint for reducing the principal amount of a specific loan payment.

    Validates input data, applies principal reduction to the target payment,
    and recalculates interest values for the modified payment and all subsequent
    payments using the Declining Balance method. All operations are executed
    atomically.
    """

    serializer_class = ReducePrincipalSerializer
    queryset = LoanPayment.objects.none()
    http_method_names = ["patch", "options"]

    def patch(self, request, *args, **kwargs):
        """
        Reduce principal for a loan payment and return updated payments list.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = get_object_or_404(
            LoanPayment,
            pk=serializer.validated_data["payment_id"],
        )

        with transaction.atomic():
            updated_payments = DecliningBalancePrincipalReducer(
                payment=payment,
                reduce_amount=serializer.validated_data["amount"],
            ).execute()

        return Response(LoanPaymentSerializer(updated_payments, many=True).data)


class AllPaymentsGroupedListView(ListAPIView):
    """
    GET endpoint that returns all loans with their related payments grouped per loan.

    Each loan includes its full list of payments ordered by payment number.
    """

    serializer_class = LoanWithPaymentsSerializer
    queryset = Loan.objects.prefetch_related("payments").order_by("id")
