"""Finance screens: Cashier payment workflow + Administrator approvals.

Authorization is enforced by role mixins on every view (server-side), not by
hidden links. Students and instructors have no finance access.
"""

import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from accounts.models import User
from accounts.permissions import (
    AssessmentManageMixin,
    CashierRequiredMixin,
    FinanceApproverMixin,
    FinanceReadMixin,
)
from accounts.services import CONFLICT_ERROR
from finance.forms import (
    AdjustmentForm,
    PaymentForm,
    ReviseAssessmentForm,
    ScholarshipForm,
)
from finance.models import (
    Adjustment,
    Assessment,
    Payment,
    ScholarshipAward,
)
from finance.services import (
    apply_scholarship,
    approve_adjustment,
    approve_scholarship,
    assessment_amount_paid,
    assessment_balance,
    create_adjustment,
    create_scholarship,
    finalize_assessment,
    record_payment,
    reject_adjustment,
    reverse_payment,
    revise_assessment,
)

logger = logging.getLogger(__name__)


def _role(request):
    return getattr(request.user, "role", None)


class AssessmentListView(FinanceReadMixin, View):
    template_name = "finance/assessment_list.html"

    def get(self, request):
        query = request.GET.get("q", "").strip()
        assessments = (
            Assessment.objects.select_related(
                "enrollment__student__user", "enrollment__term", "current_version"
            ).order_by("-assessed_at")
        )
        if query:
            assessments = assessments.filter(
                Q(enrollment__student__student_number__icontains=query)
                | Q(enrollment__student__user__first_name__icontains=query)
                | Q(enrollment__student__user__last_name__icontains=query)
                | Q(enrollment__student__user__username__icontains=query)
            )
        rows = [
            {"assessment": a, "balance": assessment_balance(assessment=a)}
            for a in assessments[:100]
        ]
        return render(request, self.template_name, {"rows": rows, "query": query})


class AssessmentDetailView(FinanceReadMixin, View):
    template_name = "finance/assessment_detail.html"

    def get(self, request, pk):
        assessment = get_object_or_404(
            Assessment.objects.select_related(
                "enrollment__student__user", "enrollment__term", "current_version"
            ),
            pk=pk,
        )
        role = _role(request)
        version = assessment.current_version
        lines = list(version.lines.all()) if version else []
        payments = list(
            assessment.payments.prefetch_related("allocations").order_by("-payment_date")
        )
        context = {
            "assessment": assessment,
            "version": version,
            "lines": lines,
            "payments": payments,
            "balance": assessment_balance(assessment=assessment),
            "amount_paid": assessment_amount_paid(assessment=assessment),
            "versions": list(assessment.versions.all()),
            "adjustments": list(assessment.adjustments.select_related("created_by", "approved_by")),
            "scholarships": list(assessment.scholarships.all()),
            "can_pay": role == User.Role.CASHIER and assessment.is_finalized,
            "can_manage": role in (User.Role.REGISTRAR, User.Role.ADMINISTRATOR),
            "can_approve": role == User.Role.ADMINISTRATOR,
            "can_create_adjustment": role in (User.Role.CASHIER, User.Role.REGISTRAR),
        }
        return render(request, self.template_name, context)


class RecordPaymentView(CashierRequiredMixin, View):
    template_name = "finance/payment_form.html"

    def _assessment(self, pk):
        return get_object_or_404(
            Assessment.objects.select_related("enrollment__student__user"), pk=pk
        )

    def get(self, request, pk):
        assessment = self._assessment(pk)
        return render(request, self.template_name, {
            "assessment": assessment, "form": PaymentForm(),
            "balance": assessment_balance(assessment=assessment),
        })

    def post(self, request, pk):
        assessment = self._assessment(pk)
        form = PaymentForm(request.POST)
        if not assessment.is_finalized:
            messages.error(request, "Payments can only be recorded against a finalized assessment.")
            return redirect("finance:assessment_detail", pk=pk)
        if form.is_valid():
            data = form.cleaned_data
            try:
                payment = record_payment(
                    assessment=assessment, received_by=request.user,
                    receipt_number=data["receipt_number"], amount=data["amount"],
                    method=data["method"], reference_note=data["reference_note"],
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            except IntegrityError:
                logger.warning("Integrity conflict recording payment in %s", self.__class__.__name__)
                form.add_error(None, CONFLICT_ERROR)
            else:
                messages.success(request, f"Payment {payment.receipt_number} recorded.")
                return redirect("finance:receipt", pk=payment.pk)
        return render(request, self.template_name, {
            "assessment": assessment, "form": form,
            "balance": assessment_balance(assessment=assessment),
        })


class ReceiptView(FinanceReadMixin, View):
    template_name = "finance/receipt.html"

    def get(self, request, pk):
        payment = get_object_or_404(
            Payment.objects.select_related(
                "assessment__enrollment__student__user", "received_by"
            ).prefetch_related("allocations"),
            pk=pk,
        )
        return render(request, self.template_name, {
            "payment": payment, "assessment": payment.assessment,
            "balance": assessment_balance(assessment=payment.assessment),
        })


class FinalizeAssessmentView(AssessmentManageMixin, View):
    def post(self, request, pk):
        assessment = get_object_or_404(Assessment, pk=pk)
        try:
            finalize_assessment(assessment=assessment, by=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Assessment finalized.")
        return redirect("finance:assessment_detail", pk=pk)


class ReviseAssessmentView(AssessmentManageMixin, View):
    template_name = "finance/revise_form.html"

    def get(self, request, pk):
        assessment = get_object_or_404(Assessment, pk=pk)
        return render(request, self.template_name, {"assessment": assessment, "form": ReviseAssessmentForm()})

    def post(self, request, pk):
        assessment = get_object_or_404(Assessment, pk=pk)
        form = ReviseAssessmentForm(request.POST)
        if form.is_valid():
            try:
                revise_assessment(assessment=assessment, by=request.user, reason=form.cleaned_data["reason"])
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, "A new draft version was created. Finalize it when ready.")
                return redirect("finance:assessment_detail", pk=pk)
        return render(request, self.template_name, {"assessment": assessment, "form": form})


class ReversePaymentView(FinanceApproverMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        reason = request.POST.get("reason", "").strip() or "Payment reversed"
        try:
            reverse_payment(payment=payment, by=request.user, reason=reason)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Payment reversed.")
        return redirect("finance:assessment_detail", pk=payment.assessment_id)


class CreateAdjustmentView(FinanceReadMixin, View):
    template_name = "finance/adjustment_form.html"

    def _check_role(self, request):
        return _role(request) in (User.Role.CASHIER, User.Role.REGISTRAR)

    def get(self, request, pk):
        assessment = get_object_or_404(Assessment, pk=pk)
        if not self._check_role(request):
            messages.error(request, "You are not permitted to create adjustments.")
            return redirect("finance:assessment_detail", pk=pk)
        return render(request, self.template_name, {"assessment": assessment, "form": AdjustmentForm()})

    def post(self, request, pk):
        assessment = get_object_or_404(Assessment, pk=pk)
        if not self._check_role(request):
            messages.error(request, "You are not permitted to create adjustments.")
            return redirect("finance:assessment_detail", pk=pk)
        form = AdjustmentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                create_adjustment(
                    adjustment_type=data["adjustment_type"], amount=data["amount"],
                    reason=data["reason"], by=request.user, assessment=assessment,
                    version=assessment.current_version,
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Adjustment submitted for approval.")
                return redirect("finance:assessment_detail", pk=pk)
        return render(request, self.template_name, {"assessment": assessment, "form": form})


class CreateScholarshipView(FinanceReadMixin, View):
    """Submit a scholarship against a specific assessment (Cashier/Registrar).

    Assessment-scoped like :class:`CreateAdjustmentView`: the student is derived
    server-side from the assessment (via the URL pk), so a submitted student
    value can never attach an award to another student's assessment. The award
    is linked to the assessment and its current version so the authoritative
    balance (``assessment_balance``) counts it once approved.
    """

    template_name = "finance/scholarship_form.html"

    def _check_role(self, request):
        return _role(request) in (User.Role.CASHIER, User.Role.REGISTRAR)

    def _assessment(self, pk):
        return get_object_or_404(
            Assessment.objects.select_related("enrollment__student__user"), pk=pk
        )

    def _guard(self, request, assessment):
        """Return a redirect response if submission is not allowed, else None."""
        if not self._check_role(request):
            messages.error(request, "You are not permitted to create scholarships.")
            return redirect("finance:assessment_detail", pk=assessment.pk)
        if assessment.current_version_id is None:
            messages.error(
                request,
                "This assessment has no active version yet, so a scholarship "
                "cannot be recorded against it.",
            )
            return redirect("finance:assessment_detail", pk=assessment.pk)
        return None

    def get(self, request, pk):
        assessment = self._assessment(pk)
        blocked = self._guard(request, assessment)
        if blocked is not None:
            return blocked
        return render(request, self.template_name, {
            "assessment": assessment, "form": ScholarshipForm(),
        })

    def post(self, request, pk):
        assessment = self._assessment(pk)
        blocked = self._guard(request, assessment)
        if blocked is not None:
            return blocked
        form = ScholarshipForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                create_scholarship(
                    student=assessment.enrollment.student,
                    sponsor=data["sponsor"], amount=data["amount"],
                    by=request.user, assessment=assessment,
                    version=assessment.current_version, is_demo=False,
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Scholarship submitted for approval.")
                return redirect("finance:assessment_detail", pk=pk)
        return render(request, self.template_name, {
            "assessment": assessment, "form": form,
        })


class ApprovalsView(FinanceApproverMixin, View):
    template_name = "finance/approvals.html"

    def get(self, request):
        return render(request, self.template_name, {
            "adjustments": Adjustment.objects.filter(status=Adjustment.Status.PENDING)
                .select_related("created_by", "assessment"),
            "scholarships": ScholarshipAward.objects.filter(status=ScholarshipAward.Status.PENDING)
                .select_related("created_by", "student__user"),
            "approved_scholarships": ScholarshipAward.objects.filter(status=ScholarshipAward.Status.APPROVED)
                .select_related("student__user"),
        })


class AdjustmentActionView(FinanceApproverMixin, View):
    def post(self, request, pk, action):
        adjustment = get_object_or_404(Adjustment, pk=pk)
        try:
            if action == "approve":
                approve_adjustment(adjustment=adjustment, by=request.user)
                messages.success(request, "Adjustment approved.")
            elif action == "reject":
                reject_adjustment(adjustment=adjustment, by=request.user)
                messages.success(request, "Adjustment rejected.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("finance:approvals")


class ScholarshipActionView(FinanceApproverMixin, View):
    def post(self, request, pk, action):
        scholarship = get_object_or_404(ScholarshipAward, pk=pk)
        try:
            if action == "approve":
                approve_scholarship(scholarship=scholarship, by=request.user)
                messages.success(request, "Scholarship approved.")
            elif action == "apply":
                apply_scholarship(scholarship=scholarship, by=request.user)
                messages.success(request, "Scholarship applied.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("finance:approvals")
