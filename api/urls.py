from django.urls import path
from .views import (
    RegisterView, LoginView,
    DonorStatsView, DonationHistoryView, BloodInventoryView, HospitalRequestsView, HospitalSearchView,
    ActiveRequestsView, HospitalListView, HospitalAppointmentsView,
    AdminStatsView, UserManagementView, AdminAlertsView, GlobalInventoryView, AdminDonorSearchView,
    AlertResponseView, NotificationView, ProfileUpdateView, AdminDonationHistoryView,
    AdminAnalyticsView, SaveFCMTokenView, ForgotPasswordView,
    
    # New Views
    CompleteRequestView, BloodBatchView, BatchActionView, IgnoreRequestView,
    DonorP2PRequestView, MyRequestsView, ActiveLocationsView, DonorCountView,
    HospitalDonorListView, HospitalReportsView, HospitalDispatchView, HospitalReceiveView
)

urlpatterns = [
    # Auth
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('profile/update/', ProfileUpdateView.as_view(), name='profile-update'),
    path('fcm/token/', SaveFCMTokenView.as_view(), name='save-fcm-token'),

    # Dashboard API - Donor
    path('donor/stats/', DonorStatsView.as_view(), name='donor-stats'),
    path('donor/history/', DonationHistoryView.as_view(), name='donor-history'),
    path('donor/active-requests/', ActiveRequestsView.as_view(), name='donor-urgent'),
    path('donor/hospitals/', HospitalListView.as_view(), name='hospital-list'),
    path('donor/respond-alert/', AlertResponseView.as_view(), name='respond-alert'),
    path('donor/ignore-request/', IgnoreRequestView.as_view(), name='ignore-request'), # New
    path('donor/requests/', DonorP2PRequestView.as_view(), name='donor-p2p-request'), # New
    path('donor/requests/complete/', CompleteRequestView.as_view(), name='donor-complete-request'), # New
    path('donor/my-requests/', MyRequestsView.as_view(), name='donor-my-requests'),

    # Dashboard API - Hospital
    path('hospital/inventory/', BloodInventoryView.as_view(), name='hospital-inventory'),
    path('hospital/requests/', HospitalRequestsView.as_view(), name='hospital-requests'),
    path('hospital/search/', HospitalSearchView.as_view(), name='hospital-search'),
    path('hospital/appointments/', HospitalAppointmentsView.as_view(), name='hospital-appointments'),
    
    # New Hospital Features
    path('hospital/donors/', HospitalDonorListView.as_view(), name='hospital-donors'),
    path('hospital/reports/', HospitalReportsView.as_view(), name='hospital-reports'),
    path('hospital/dispatch/', HospitalDispatchView.as_view(), name='hospital-dispatch'),
    path('hospital/receive/', HospitalReceiveView.as_view(), name='hospital-receive'),
    
    # Batch Management
    path('hospital/batches/', BloodBatchView.as_view(), name='hospital-batches'),
    path('hospital/batches/action/', BatchActionView.as_view(), name='hospital-batch-action'),

    # Admin API (Functionality kept for potential superadmin, but UI removed)
    path('admin/stats/', AdminStatsView.as_view(), name='admin-stats'),
    path('admin/users/', UserManagementView.as_view(), name='admin-users'),
    path('admin/alerts/', AdminAlertsView.as_view(), name='admin-alerts'),
    path('admin/search-donors/', AdminDonorSearchView.as_view(), name='admin-search-donors'),
    path('admin/inventory/', GlobalInventoryView.as_view(), name='admin-inventory'),
    path('admin/history/', AdminDonationHistoryView.as_view(), name='admin-history'),
    path('admin/analytics/', AdminAnalyticsView.as_view(), name='admin-analytics'),

    # Notifications
    path('notifications/', NotificationView.as_view(), name='notifications'),
    path('locations/active/', ActiveLocationsView.as_view(), name='active-locations'),
    path('locations/count/', DonorCountView.as_view(), name='location-count'),
]
