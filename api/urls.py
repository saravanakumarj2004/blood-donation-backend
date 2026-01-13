from django.urls import path
from .views import (
    RegisterView, LoginView,
    DonorStatsView, DonationHistoryView, BloodInventoryView, HospitalRequestsView, HospitalSearchView,
    ActiveRequestsView, HospitalListView, HospitalAppointmentsView,
    AdminStatsView, UserManagementView, AdminAlertsView, GlobalInventoryView, AdminDonorSearchView,
    AlertResponseView, NotificationView, ProfileUpdateView, AdminDonationHistoryView,
    AdminAnalyticsView
)

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),

    # Dashboard API
    path('donor/stats/', DonorStatsView.as_view(), name='donor-stats'),
    path('donor/history/', DonationHistoryView.as_view(), name='donor-history'),
    
    path('hospital/inventory/', BloodInventoryView.as_view(), name='hospital-inventory'),
    path('hospital/requests/', HospitalRequestsView.as_view(), name='hospital-requests'),
    path('hospital/search/', HospitalSearchView.as_view(), name='hospital-search'),

    # Donor Urgent Requests
    # Donor Urgent Requests
    path('donor/active-requests/', ActiveRequestsView.as_view(), name='donor-urgent'),
    path('donor/hospitals/', HospitalListView.as_view(), name='hospital-list'),

    # Hospital Appointments
    path('hospital/appointments/', HospitalAppointmentsView.as_view(), name='hospital-appointments'),

    # Admin API
    path('admin/stats/', AdminStatsView.as_view(), name='admin-stats'),
    path('admin/users/', UserManagementView.as_view(), name='admin-users'),
    path('admin/alerts/', AdminAlertsView.as_view(), name='admin-alerts'),
    path('admin/search-donors/', AdminDonorSearchView.as_view(), name='admin-search-donors'),
    path('admin/inventory/', GlobalInventoryView.as_view(), name='admin-inventory'),
    path('donor/respond-alert/', AlertResponseView.as_view(), name='respond-alert'),
    path('notifications/', NotificationView.as_view(), name='notifications'),
    path('admin/history/', AdminDonationHistoryView.as_view(), name='admin-history'),
    path('admin/analytics/', AdminAnalyticsView.as_view(), name='admin-analytics'),
    path('profile/update/', ProfileUpdateView.as_view(), name='profile-update'),
]
