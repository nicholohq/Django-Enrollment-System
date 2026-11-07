from django.urls import path

from finance import views

app_name = "finance"

urlpatterns = [
    path("", views.AssessmentListView.as_view(), name="assessment_list"),
    path("assessment/<int:pk>/scholarship/new/", views.CreateScholarshipView.as_view(), name="scholarship_create"),
    path("approvals/", views.ApprovalsView.as_view(), name="approvals"),
    path("approvals/adjustment/<int:pk>/<str:action>/", views.AdjustmentActionView.as_view(), name="adjustment_action"),
    path("approvals/scholarship/<int:pk>/<str:action>/", views.ScholarshipActionView.as_view(), name="scholarship_action"),
    path("assessment/<int:pk>/", views.AssessmentDetailView.as_view(), name="assessment_detail"),
    path("assessment/<int:pk>/pay/", views.RecordPaymentView.as_view(), name="record_payment"),
    path("assessment/<int:pk>/finalize/", views.FinalizeAssessmentView.as_view(), name="finalize"),
    path("assessment/<int:pk>/revise/", views.ReviseAssessmentView.as_view(), name="revise"),
    path("assessment/<int:pk>/adjustment/new/", views.CreateAdjustmentView.as_view(), name="adjustment_create"),
    path("payment/<int:pk>/receipt/", views.ReceiptView.as_view(), name="receipt"),
    path("payment/<int:pk>/reverse/", views.ReversePaymentView.as_view(), name="reverse_payment"),
]
