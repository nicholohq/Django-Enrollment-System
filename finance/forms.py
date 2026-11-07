"""Forms for the finance (Cashier/Administrator) screens."""

from django import forms

from accounts.forms import BootstrapFormMixin
from finance.models import Adjustment, Payment, ScholarshipAward


class PaymentForm(BootstrapFormMixin, forms.Form):
    receipt_number = forms.CharField(max_length=40)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=Payment.Method.choices)
    reference_note = forms.CharField(max_length=120, required=False)


class AdjustmentForm(BootstrapFormMixin, forms.Form):
    # Only the two adjustment types that actually affect the balance are offered.
    # CORRECTION is a non-financial model/annotation type and REVERSAL is created
    # solely by the payment-reverse flow — neither is selectable here (a tampered
    # POST with those values fails ChoiceField validation server-side).
    adjustment_type = forms.ChoiceField(
        choices=[
            (Adjustment.Type.CREDIT, Adjustment.Type.CREDIT.label),
            (Adjustment.Type.REFUND, Adjustment.Type.REFUND.label),
        ],
        help_text="Credit reduces the balance; Refund increases the amount owed.",
    )
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    reason = forms.CharField(max_length=255)


class ReviseAssessmentForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(max_length=255, label="Revision reason")


class ScholarshipForm(BootstrapFormMixin, forms.Form):
    # The student and assessment are derived server-side from the assessment URL
    # (see finance.views.CreateScholarshipView), never from submitted input.
    sponsor = forms.CharField(max_length=150)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
