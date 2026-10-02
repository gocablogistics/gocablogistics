# Import all views to make them available from gocabapp.views
from .auth_views import (
    home,
    signup,
    upgrade_to_driver,
    signin,
    logout_view,
    switch_role,
)
from .rider_views import rider_dashboard, request_ride, cancel_ride, ride_status
from .driver_views import (
    driver_dashboard,
    driver_profile,
    driver_earnings,
    pending_rides,
    accepted_rides,
    active_rides,
    update_driver_location,
    accept_ride,
    start_trip,
    complete_trip,
    completed_trips,
    driver_cancel_ride,
)
from .payment_views import estimate_fare, initiate_payment, payment_success

# This maintains backward compatibility with your existing imports
__all__ = [
    # Auth views
    "home",
    "signup",
    "upgrade_to_driver",
    "signin",
    "logout_view",
    "switch_role",
    # Rider views
    "rider_dashboard",
    "request_ride",
    "cancel_ride",
    "ride_status",
    # Driver views
    "driver_dashboard",
    "driver_profile",
    "driver_earnings",
    "pending_rides",
    "accepted_rides",
    "active_rides",
    "update_driver_location",
    "accept_ride",
    "start_trip",
    "complete_trip",
    "completed_trips",
    "driver_cancel_ride",
    # Payment views
    "estimate_fare",
    "initiate_payment",
    "payment_success",
]
