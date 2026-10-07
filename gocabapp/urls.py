from django.urls import path
from . import views
from .views import estimate_fare



urlpatterns = [
    path("request_ride/", views.request_ride, name="request_ride"),
    path("cancel-ride/<int:ride_id>/", views.cancel_ride, name="cancel_ride"),
    path("driver/accept-ride/<int:ride_id>/", views.accept_ride, name="accept_ride"),
    path("driver/start-trip/<int:ride_id>/", views.start_trip, name="start_trip"),
    path(
        "driver/complete-trip/<int:ride_id>/", views.complete_trip, name="complete_trip"
    ),
    path("api/estimate-fare/", estimate_fare, name="estimate_fare"),
    path("ride-status/<int:ride_id>/", views.ride_status, name="ride_status"),
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
]
