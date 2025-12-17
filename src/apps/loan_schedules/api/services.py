from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.db import models, transaction

from apps.loan_schedules.models import Loan, LoanPayment


@dataclass(frozen=True)
class Period:
    """
    Represents a payment period parsed from a periodicity string.

    value: numeric multiplier of the period
    unit: period unit (d = days, w = weeks, m = months)
    """

    value: int
    unit: str

    @classmethod
    def from_string(cls, periodicity: str) -> "Period":
        """
        Parse periodicity string into Period object.

        Expected format: <positive integer><unit>,
        where unit is one of: d, w, m.
        Example: 1m, 2w, 10d.
        """
        if not periodicity or len(periodicity) < 2:
            raise ValueError("Invalid periodicity")

        value = int(periodicity[:-1])
        unit = periodicity[-1]

        if unit not in {"d", "w", "m"} or value <= 0:
            raise ValueError("Invalid periodicity")

        return cls(value=value, unit=unit)


class DateCalculator:
    """
    Utility class for calculating next payment dates based on period.
    """

    _ADD_PERIOD = {
        "d": lambda d, v: d + timedelta(days=v),
        "w": lambda d, v: d + timedelta(weeks=v),
        "m": lambda d, v: d + relativedelta(months=v),
    }

    @classmethod
    def add_period(cls, base_date: date, period: Period) -> date:
        """
        Add a period to the given base date and return the new date.
        """
        try:
            return cls._ADD_PERIOD[period.unit](base_date, period.value)
        except KeyError:
            raise ValueError("Invalid period unit")


class InterestRateCalculator:
    """
    Calculates interest rate per payment period from annual rate.
    """

    _YEAR_FRACTION = {
        "d": Decimal(1) / Decimal(365),
        "w": Decimal(1) / Decimal(52),
        "m": Decimal(1) / Decimal(12),
    }

    @classmethod
    def rate_per_period(
        cls,
        annual_rate: Decimal,
        period: Period,
    ) -> Decimal:
        """
        Convert annual interest rate to interest rate per payment period.
        """
        try:
            fraction = cls._YEAR_FRACTION[period.unit] * Decimal(period.value)
        except KeyError:
            raise ValueError("Invalid period unit")

        return (annual_rate * fraction).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_HALF_UP,
        )


class EMICalculator:
    """
    Calculates EMI (Equated Monthly Installment) value.
    """

    @staticmethod
    def calculate(
        principal: Decimal,
        rate_per_period: Decimal,
        number_of_payments: int,
    ) -> Decimal:
        """
        Calculate EMI based on principal, rate per period and number of payments.
        """
        one = Decimal("1")

        if rate_per_period == 0:
            return (principal / Decimal(number_of_payments)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        emi = (
            rate_per_period
            * principal
            / (one - (one + rate_per_period) ** Decimal(-number_of_payments))
        )

        return emi.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


class DecliningBalanceScheduleGenerator:
    """
    Generates a loan repayment schedule using declining balance method.
    """

    def __init__(
        self,
        *,
        amount: Decimal,
        start_date: date,
        number_of_payments: int,
        periodicity: str,
        interest_rate: Decimal,
    ):
        """
        Initialize schedule generator with loan parameters.
        """
        self.amount = amount
        self.start_date = start_date
        self.number_of_payments = number_of_payments
        self.period = Period.from_string(periodicity)
        self.rate_per_period = InterestRateCalculator.rate_per_period(
            interest_rate,
            self.period,
        )
        self.emi = EMICalculator.calculate(
            amount,
            self.rate_per_period,
            number_of_payments,
        )

    def generate(self) -> list[dict]:
        """
        Generate payment schedule.

        Returns list of payments with payment number, date,
        principal part and interest part.
        """
        remaining_principal = self.amount
        payment_date = self.start_date
        payments: list[dict] = []

        for payment_number in range(1, self.number_of_payments + 1):
            interest = (remaining_principal * self.rate_per_period).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            principal = (self.emi - interest).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            if payment_number == self.number_of_payments:
                principal = remaining_principal
                interest = (self.emi - principal).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )

            payments.append(
                {
                    "payment_number": payment_number,
                    "date": payment_date,
                    "principal": principal,
                    "interest": interest,
                }
            )

            remaining_principal -= principal
            payment_date = DateCalculator.add_period(payment_date, self.period)

        return payments


def generate_schedule(
    *,
    amount: Decimal,
    start_date: date,
    number_of_payments: int,
    periodicity: str,
    interest_rate: Decimal,
) -> list[dict]:
    """
    Convenience function to generate declining balance loan schedule.
    """
    return DecliningBalanceScheduleGenerator(
        amount=amount,
        start_date=start_date,
        number_of_payments=number_of_payments,
        periodicity=periodicity,
        interest_rate=interest_rate,
    ).generate()


class DecliningBalancePrincipalReducer:
    """
    Service class for reducing principal of a single loan payment and
    recalculating interests and principals for this and all subsequent payments
    using the Declining Balance (EMI-based) method.
    """

    def __init__(
        self,
        *,
        payment: LoanPayment,
        reduce_amount: Decimal,
    ):
        """
        Initialize reducer with target payment and reduction amount.

        Resolves related loan, payment period, and interest rate per period.
        """
        self.payment = payment
        self.reduce_amount = reduce_amount
        self.loan = payment.loan

        self.period = Period.from_string(self.loan.periodicity)
        self.rate_per_period = InterestRateCalculator.rate_per_period(
            self.loan.interest_rate,
            self.period,
        )

    def execute(self) -> list[LoanPayment]:
        """
        Execute principal reduction and full recalculation flow.

        Validates reduction, applies fixed principal to the target payment,
        recalculates interest and principal values for all subsequent payments,
        and returns the updated payments list.
        """
        with transaction.atomic():
            self._validate()
            self._apply_principal_reduction()
            self._recalculate_from_payment()

        return list(
            LoanPayment.objects.filter(
                loan=self.loan,
                payment_number__gte=self.payment.payment_number,
            ).order_by("payment_number")
        )

    def _validate(self) -> None:
        """
        Validate reduction amount against business rules.
        """
        if self.reduce_amount <= 0:
            raise ValueError("Reduction amount must be positive")

        if self.reduce_amount >= self.payment.principal:
            raise ValueError("Reduction exceeds payment principal")

    def _apply_principal_reduction(self) -> None:
        """
        Apply principal reduction to the selected payment and
        mark it as fixed to prevent further recalculation.
        """
        self.payment.principal = (self.payment.principal - self.reduce_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        self.payment.is_principal_fixed = True
        self.payment.save(update_fields=["principal", "is_principal_fixed"])

    def _recalculate_from_payment(self) -> None:
        """
        Recalculate principal and interest for the target payment
        and all subsequent payments based on updated balance.
        """
        payments = list(
            LoanPayment.objects.filter(
                loan=self.loan,
                payment_number__gte=self.payment.payment_number,
            ).order_by("payment_number")
        )

        balance = self._balance_before_payment()

        remaining_payments = len(payments)

        emi = EMICalculator.calculate(
            principal=balance,
            rate_per_period=self.rate_per_period,
            number_of_payments=remaining_payments,
        )

        for idx, payment in enumerate(payments):
            is_last = idx == remaining_payments - 1

            interest = (balance * self.rate_per_period).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            if payment.is_principal_fixed:
                principal = payment.principal

            elif is_last:
                principal = balance

            else:
                principal = (emi - interest).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )

            payment.principal = principal
            payment.interest = interest
            payment.save(update_fields=["principal", "interest"])

            balance = (balance - principal).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

    def _balance_before_payment(self) -> Decimal:
        """
        Calculate remaining loan balance before the target payment.
        """
        paid = LoanPayment.objects.filter(
            loan=self.loan,
            payment_number__lt=self.payment.payment_number,
        ).aggregate(total=models.Sum("principal"))["total"] or Decimal("0.00")

        return (self.loan.amount - paid).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
