from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import models
from django.urls import reverse

from apps.loan_schedules.api.services import (
    DateCalculator,
    DecliningBalancePrincipalReducer,
    InterestRateCalculator,
    Period,
    generate_schedule,
)
from apps.loan_schedules.models import Loan, LoanPayment

pytestmark = pytest.mark.django_db


@pytest.fixture
def loan():
    return Loan.objects.create(
        amount=Decimal("1000.00"),
        interest_rate=Decimal("0.12"),
        loan_start_date=date(2027, 1, 1),
        number_of_payments=4,
        periodicity="1m",
    )


@pytest.fixture
def loan_with_payments(loan):
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
                payment_number=p["payment_number"],
                payment_date=p["date"],
                principal=p["principal"],
                interest=p["interest"],
            )
            for p in payments
        ]
    )

    return loan


class TestScheduleGeneration:
    def test_schedule_payments_count(self, loan_with_payments):
        assert loan_with_payments.payments.count() == 4

    def test_schedule_principal_sum_equals_loan_amount(self, loan_with_payments):
        total_principal = loan_with_payments.payments.aggregate(
            total=models.Sum("principal")
        )["total"]

        assert total_principal.quantize(Decimal("0.01")) == Decimal("1000.00")

    def test_schedule_payment_numbers_ordered(self, loan_with_payments):
        numbers = list(
            loan_with_payments.payments.values_list("payment_number", flat=True)
        )
        assert numbers == [1, 2, 3, 4]


class TestPrincipalReducer:
    def test_reduce_principal_updates_current_payment_only(self, loan_with_payments):
        payment = loan_with_payments.payments.get(payment_number=2)
        original_principal = payment.principal

        updated = DecliningBalancePrincipalReducer(
            payment=payment,
            reduce_amount=Decimal("50.00"),
        ).execute()

        payment.refresh_from_db()

        assert payment.principal == original_principal - Decimal("50.00")
        assert payment.is_principal_fixed is True
        assert len(updated) == 3

    def test_reduce_principal_recalculates_subsequent_payments(
        self, loan_with_payments
    ):
        payment = loan_with_payments.payments.get(payment_number=2)

        old_interests = list(
            loan_with_payments.payments.filter(payment_number__gte=2).values_list(
                "interest", flat=True
            )
        )

        DecliningBalancePrincipalReducer(
            payment=payment,
            reduce_amount=Decimal("100.00"),
        ).execute()

        new_interests = list(
            loan_with_payments.payments.filter(payment_number__gte=2).values_list(
                "interest", flat=True
            )
        )

        assert old_interests != new_interests

    def test_reduce_principal_invalid_amount_raises(self, loan_with_payments):
        payment = loan_with_payments.payments.first()

        with pytest.raises(ValueError):
            DecliningBalancePrincipalReducer(
                payment=payment,
                reduce_amount=Decimal("0.00"),
            ).execute()

        with pytest.raises(ValueError):
            DecliningBalancePrincipalReducer(
                payment=payment,
                reduce_amount=payment.principal,
            ).execute()


class TestAPI:
    def test_create_loan_schedule_api(self, client):
        url = reverse("loan-create")

        payload = {
            "amount": "1000.00",
            "interest_rate": "0.12",
            "loan_start_date": "17-12-2027",
            "number_of_payments": 4,
            "periodicity": "1m",
        }

        response = client.post(url, payload, content_type="application/json")

        assert response.status_code == 200
        assert len(response.json()) == 4

    def test_reduce_principal_api(self, client, loan_with_payments):
        payment = loan_with_payments.payments.get(payment_number=2)

        url = reverse("loan-payment-reduce-principal")

        payload = {
            "payment_id": payment.id,
            "amount": "50.00",
        }

        response = client.patch(url, payload, content_type="application/json")

        assert response.status_code == 200
        data = response.json()

        assert data[0]["id"] == payment.id
        assert Decimal(data[0]["principal"]) < payment.principal

    def test_grouped_payments_list_api(self, client, loan_with_payments):
        url = reverse("all-payments-grouped")

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()

        assert len(data) == 1
        assert "payments" in data[0]
        assert len(data[0]["payments"]) == 4


class TestPrincipalReducerAdvanced:
    def test_reduction_does_not_affect_previous_payments(self, loan_with_payments):
        p1 = loan_with_payments.payments.get(payment_number=1)
        p2 = loan_with_payments.payments.get(payment_number=2)

        DecliningBalancePrincipalReducer(
            payment=p2,
            reduce_amount=Decimal("50.00"),
        ).execute()

        p1.refresh_from_db()
        assert p1.is_principal_fixed is False

    def test_multiple_reductions_on_different_payments(self, loan_with_payments):
        p2 = loan_with_payments.payments.get(payment_number=2)
        p3 = loan_with_payments.payments.get(payment_number=3)

        DecliningBalancePrincipalReducer(
            payment=p2,
            reduce_amount=Decimal("30.00"),
        ).execute()

        DecliningBalancePrincipalReducer(
            payment=p3,
            reduce_amount=Decimal("20.00"),
        ).execute()

        p2.refresh_from_db()
        p3.refresh_from_db()

        assert p2.is_principal_fixed
        assert p3.is_principal_fixed

    def test_balance_reaches_zero_at_end(self, loan_with_payments):
        payments = loan_with_payments.payments.order_by("payment_number")
        last_payment = payments.last()

        remaining = (
            loan_with_payments.amount
            - payments.exclude(id=last_payment.id).aggregate(
                total=models.Sum("principal")
            )["total"]
        )

        assert remaining.quantize(Decimal("0.01")) == last_payment.principal


class TestScheduleEdgeCases:
    def test_zero_interest_rate(self, loan):
        loan.interest_rate = Decimal("0.00")
        loan.save()

        payments = generate_schedule(
            amount=loan.amount,
            start_date=loan.loan_start_date,
            number_of_payments=loan.number_of_payments,
            periodicity=loan.periodicity,
            interest_rate=loan.interest_rate,
        )

        interests = [p["interest"] for p in payments]
        assert all(i == Decimal("0.00") for i in interests)

    def test_single_payment_schedule(self, loan):
        loan.number_of_payments = 1
        loan.save()

        payments = generate_schedule(
            amount=loan.amount,
            start_date=loan.loan_start_date,
            number_of_payments=1,
            periodicity=loan.periodicity,
            interest_rate=loan.interest_rate,
        )

        assert len(payments) == 1
        assert payments[0]["principal"] == loan.amount

    def test_schedule_dates_increment_monthly(self, loan):
        payments = generate_schedule(
            amount=loan.amount,
            start_date=loan.loan_start_date,
            number_of_payments=loan.number_of_payments,
            periodicity="1m",
            interest_rate=loan.interest_rate,
        )

        assert payments[1]["date"].month == 2
        assert payments[2]["date"].month == 3

    def test_schedule_dates_increment_weekly(self, loan):
        payments = generate_schedule(
            amount=loan.amount,
            start_date=loan.loan_start_date,
            number_of_payments=loan.number_of_payments,
            periodicity="1w",
            interest_rate=loan.interest_rate,
        )

        delta = payments[1]["date"] - payments[0]["date"]
        assert delta.days == 7

    def test_schedule_principal_never_negative(self, loan):
        payments = generate_schedule(
            amount=loan.amount,
            start_date=loan.loan_start_date,
            number_of_payments=loan.number_of_payments,
            periodicity=loan.periodicity,
            interest_rate=loan.interest_rate,
        )

        assert all(p["principal"] > 0 for p in payments)


class TestPeriodParsing:
    def test_valid_periods(self):
        p = Period.from_string("2w")
        assert p.value == 2
        assert p.unit == "w"

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            Period.from_string("0m")

        with pytest.raises(ValueError):
            Period.from_string("10x")

        with pytest.raises(ValueError):
            Period.from_string("m")


class TestDateCalculator:
    def test_add_month(self):
        d = date(2027, 1, 31)
        new_date = DateCalculator.add_period(d, Period(1, "m"))
        assert new_date.month == 2

    def test_add_day(self):
        d = date(2027, 1, 1)
        new_date = DateCalculator.add_period(d, Period(10, "d"))
        assert new_date.day == 11


class TestInterestRateCalculator:
    def test_monthly_rate(self):
        rate = InterestRateCalculator.rate_per_period(
            Decimal("0.12"),
            Period(1, "m"),
        )
        assert rate.quantize(Decimal("0.0001")) == Decimal("0.0100")

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError):
            InterestRateCalculator.rate_per_period(
                Decimal("0.12"),
                Period(1, "x"),
            )


class TestAPIErrors:
    def test_create_loan_invalid_payload(self, client):
        url = reverse("loan-create")

        response = client.post(
            url,
            {"amount": "abc"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_reduce_principal_invalid_amount(self, client, loan_with_payments):
        payment = loan_with_payments.payments.first()

        url = reverse("loan-payment-reduce-principal")

        response = client.patch(
            url,
            {
                "payment_id": payment.id,
                "amount": "0.00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_reduce_principal_payment_not_found(self, client):
        url = reverse("loan-payment-reduce-principal")

        response = client.patch(
            url,
            {
                "payment_id": 999999,
                "amount": "10.00",
            },
            content_type="application/json",
        )

        assert response.status_code == 404


class TestFullFlow:
    def test_create_then_reduce_then_list(self, client):
        create_url = reverse("loan-create")

        response = client.post(
            create_url,
            {
                "amount": "500.00",
                "interest_rate": "0.10",
                "loan_start_date": "17-12-2027",
                "number_of_payments": 2,
                "periodicity": "1m",
            },
            content_type="application/json",
        )

        assert response.status_code == 200, response.json()

        payments = response.json()
        assert isinstance(payments, list)
        assert len(payments) == 2

        payment_id = payments[0]["id"]

        reduce_url = reverse("loan-payment-reduce-principal")

        reduce_response = client.patch(
            reduce_url,
            {
                "payment_id": payment_id,
                "amount": "50.00",
            },
            content_type="application/json",
        )

        assert reduce_response.status_code == 200, reduce_response.json()

        list_url = reverse("all-payments-grouped")
        list_response = client.get(list_url)

        assert list_response.status_code == 200

        data = list_response.json()
        assert len(data) == 1
        assert len(data[0]["payments"]) == 2


def test_principal_sum_is_constant_after_reduction(loan_with_payments):
    total_before = loan_with_payments.payments.aggregate(total=models.Sum("principal"))[
        "total"
    ]

    payment = loan_with_payments.payments.get(payment_number=2)

    DecliningBalancePrincipalReducer(
        payment=payment,
        reduce_amount=Decimal("50.00"),
    ).execute()

    total_after = loan_with_payments.payments.aggregate(total=models.Sum("principal"))[
        "total"
    ]

    assert total_before == total_after == loan_with_payments.amount


def test_reduction_is_atomic_on_failure(loan_with_payments):
    payment = loan_with_payments.payments.get(payment_number=2)

    with patch(
        "apps.loan_schedules.api.services.EMICalculator.calculate",
        side_effect=Exception("boom"),
    ):
        with pytest.raises(Exception):
            DecliningBalancePrincipalReducer(
                payment=payment,
                reduce_amount=Decimal("10.00"),
            ).execute()

    payment.refresh_from_db()
    assert payment.is_principal_fixed is False


def test_reduce_principal_serializer_validation():
    from apps.loan_schedules.api.serializers import ReducePrincipalSerializer

    serializer = ReducePrincipalSerializer(data={"amount": "-10"})
    assert not serializer.is_valid()


def test_loan_create_serializer_invalid_periodicity():
    from apps.loan_schedules.api.serializers import LoanCreateSerializer

    serializer = LoanCreateSerializer(
        data={
            "amount": "1000",
            "interest_rate": "0.1",
            "loan_start_date": "2025-01-01",
            "number_of_payments": 4,
            "periodicity": "10x",
        }
    )

    assert not serializer.is_valid()
