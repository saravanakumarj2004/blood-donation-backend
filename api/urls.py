from django.urls import path
from .views import (
    RegisterView, LoginView, ForgotPasswordView,
    DonorStatsView, DonationHistoryView, BloodInventoryView, HospitalRequestsView, HospitalSearchView,
    ActiveRequestsView, HospitalListView, HospitalAppointmentsView, 
    AlertResponseView, NotificationView, ProfileUpdateView,
    ActiveLocationsView, LocationCountView, HospitalDonorSearchView,
    BatchView, BatchActionView, 
    HospitalReportsView, BloodDispatchView, BloodReceiveView,
    DonorIgnoreRequestView, DonorP2PView,
    DonorProfileView, FCMTokenView, EmailConfigView, TestEmailView
)

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),

    # Dashboard API
    path('donor/stats/', DonorStatsView.as_view(), name='donor-stats'),
    path('donor/history/', DonationHistoryView.as_view(), name='donor-history'),
    
    path('hospital/inventory/', BloodInventoryView.as_view(), name='hospital-inventory'),
    path('hospital/requests/', HospitalRequestsView.as_view(), name='hospital-requests'),
    path('hospital/search/', HospitalSearchView.as_view(), name='hospital-search'),
    
    # Batch Management
    path('hospital/batches/', BatchView.as_view(), name='hospital-batches'),
    path('hospital/batches/action/', BatchActionView.as_view(), name='hospital-batch-action'),

    # Donor Urgent Requests
    path('donor/active-requests/', ActiveRequestsView.as_view(), name='donor-urgent'),
    path('donor/hospitals/', HospitalListView.as_view(), name='hospital-list'),

    # Hospital Appointments
    path('hospital/appointments/', HospitalAppointmentsView.as_view(), name='hospital-appointments'),

    # Shared API (Notifications/Profile)
    path('donor/respond-alert/', AlertResponseView.as_view(), name='respond-alert'),
    path('notifications/', NotificationView.as_view(), name='notifications'),
    path('profile/update/', ProfileUpdateView.as_view(), name='profile-update'),
    
    path('locations/active/', ActiveLocationsView.as_view(), name='locations-active'),
    path('locations/count/', LocationCountView.as_view(), name='locations-count'),
    path('hospital/donors/', HospitalDonorSearchView.as_view(), name='hospital-donors'),

    # New Logic: Reports & P2P Dispatch
    path('hospital/reports/', HospitalReportsView.as_view(), name='hospital-reports'),
    path('hospital/dispatch/', BloodDispatchView.as_view(), name='hospital-dispatch'),
    path('hospital/receive/', BloodReceiveView.as_view(), name='hospital-receive'),

    # Donor Logic (P2P & Actions)
    path('donor/ignore-request/', DonorIgnoreRequestView.as_view(), name='donor-ignore'),
    path('donor/my-requests/', DonorP2PView.as_view(), name='donor-my-requests'),
    path('donor/requests/', DonorP2PView.as_view(), name='donor-create-request'),
    path('donor/requests/complete/', DonorP2PView.as_view(), name='donor-complete-request'),

    # App Specific
    path('donor/profile/', DonorProfileView.as_view(), name='donor-profile'),
    path('fcm/token/', FCMTokenView.as_view(), name='fcm-token'),
    
    # Debug
    path('email-config/', EmailConfigView.as_view(), name='email-config'),
    path('test-email/', TestEmailView.as_view(), name='test-email'),
]
