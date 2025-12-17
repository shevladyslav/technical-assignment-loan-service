from django.urls import path

from .views import (
    AllPaymentsGroupedListView,
    LoanCreateScheduleView,
    ReducePrincipalView,
)

urlpatterns = [
    path("loans/", LoanCreateScheduleView.as_view(), name="loan-create"),
    path(
        "loans/payments/",
        AllPaymentsGroupedListView.as_view(),
        name="all-payments-grouped",
    ),
    path(
        "loans/reduce-principal/",
        ReducePrincipalView.as_view(),
        name="loan-payment-reduce-principal",
    ),
]
