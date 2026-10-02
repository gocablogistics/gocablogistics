from django.urls import path
from . import views
from .views import estimate_fare



urlpatterns = [
    path("", views.home, name="home"),
    path("signin/", views.signin, name="signin"),
    path("signup/", views.signup, name="signup"),
    path("get-a-ride/", views.signup, {"default_role": "rider"}, name="getaride"),
    path("become-a-driver/", views.signup, {"default_role": "driver"}, name="becomeadriver"),
    path("upgrade-to-driver/", views.upgrade_to_driver, name="upgrade_to_driver"),
    path("switch-role/<str:role>/", views.switch_role, name="switch_role"),
    path("driver-dashboard/", views.driver_dashboard, name="driver_dashboard"),
    path("driver-profile/", views.driver_profile, name="driver_profile"),
    path("rider-dashboard/", views.rider_dashboard, name="rider_dashboard"),
    path("request_ride/", views.request_ride, name="request_ride"),
    path("cancel-ride/<int:ride_id>/", views.cancel_ride, name="cancel_ride"),
    path("driver/accept-ride/<int:ride_id>/", views.accept_ride, name="accept_ride"),
    path("driver/start-trip/<int:ride_id>/", views.start_trip, name="start_trip"),
    path(
        "driver/complete-trip/<int:ride_id>/", views.complete_trip, name="complete_trip"
    ),
    path("driver/completed-trips/", views.completed_trips, name="completed_trips"),
    path("api/estimate-fare/", estimate_fare, name="estimate_fare"),
    path("ride-status/<int:ride_id>/", views.ride_status, name="ride_status"),
    path("driver/pending-rides/", views.pending_rides, name="pending_rides"),
    path("driver/accepted-rides/", views.accepted_rides, name="accepted_rides"),
    path("driver/active-rides/", views.active_rides, name="active_rides"),
    path(
        "driver/cancel-ride/<int:ride_id>/",
        views.driver_cancel_ride,
        name="driver_cancel_ride",
    ),
    path(
        "initiate-payment/<int:ride_id>/",
        views.initiate_payment,
        name="initiate_payment",
    ),
    path(
        "payment/success/<int:ride_id>/", views.payment_success, name="payment_success"
    ),
    path(
        "driver/update-driver-location/",
        views.update_driver_location,
        name="update_driver_location",
    ),
    path("logout/", views.logout_view, name="logout"),
]
