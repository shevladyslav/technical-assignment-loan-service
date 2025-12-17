from django.db import models


class Loan(models.Model):
    """
    Represents a loan entity that stores initial loan parameters
    used to generate a repayment schedule.
    """

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Total loan amount (principal) issued to the borrower",
    )
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        help_text="Interest rate for the loan (e.g. 0.1 for 10%)",
    )
    loan_start_date = models.DateField(
        help_text="Start date of the loan in YYYY-MM-DD format",
    )
    number_of_payments = models.PositiveIntegerField(
        help_text="Total number of payments in the repayment schedule",
    )
    periodicity = models.CharField(
        max_length=4,
        help_text='Payment periodicity (e.g. "1d", "5d", "2w", "3m")',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the loan was created",
    )

    def __str__(self):
        return f"Loan #{self.pk} | amount={self.amount}"

    def __repr__(self):
        return (
            f"<Loan id={self.pk} amount={self.amount} "
            f"interest_rate={self.interest_rate}>"
        )


class LoanPayment(models.Model):
    """
    Represents a single payment in a loan repayment schedule.
    """

    loan = models.ForeignKey(
        Loan,
        related_name="payments",
        on_delete=models.CASCADE,
        help_text="Reference to the related loan",
    )
    payment_number = models.PositiveIntegerField(
        help_text="Sequential number of the payment in the schedule (starting from 1)",
    )
    payment_date = models.DateField(
        help_text="Scheduled date for this payment",
    )
    principal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Principal amount to be paid in this payment",
    )
    interest = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Interest amount to be paid in this payment",
    )
    is_principal_fixed = models.BooleanField(
        default=False,
        help_text="Indicates whether the principal amount is fixed and should not be recalculated",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the payment record was created",
    )

    class Meta:
        unique_together = ("loan", "payment_number")
        ordering = ["payment_number"]

    def __str__(self):
        return f"LoanPayment #{self.payment_number} for Loan #{self.loan.pk}"

    def __repr__(self):
        return (
            f"<LoanPayment loan_id={self.loan.pk} "
            f"payment_number={self.payment_number} "
            f"principal={self.principal} interest={self.interest}>"
        )
