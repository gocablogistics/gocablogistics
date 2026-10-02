from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from ninja import Schema

VehicleType = Literal["Bike", "Bicycle"]


class RideMessageOut(Schema):
    id: int
    ride_id: int
    sender_id: int
    sender_role: str
    text: str
    created_at: datetime


class SendMessageIn(Schema):
    text: str


class RideHistoryOut(Schema):
    ride_id: int
    current_location: str
    destination: str
    status: str
    payment_status: str
    payment_method: str
    total_fare: Optional[float] = None
    distance_km: Optional[float] = None
    requested_at: datetime
    completed_at: Optional[datetime] = None
    other_party_name: Optional[str] = None
    # Only set when a PaymentDispute exists on this ride — lets the rider or
    # driver see they've been reported (or reported someone) and whether
    # it's still open for their own response, straight from ride history,
    # since a dispute can easily outlive the ride's spot on an active-ride
    # screen. my_statement_submitted is scoped to whichever side is asking.
    dispute_status: Optional[str] = None
    my_statement_submitted: bool = False
    my_rating_submitted: bool = False


class FareEstimateIn(Schema):
    pickup: str
    destination: str
    vehicle_type: VehicleType = "Bike"


class FareEstimateOut(Schema):
    base_fare: float
    distance_km: float
    duration_min: float
    distance_fare: float
    time_fare: float
    surge_multiplier: float
    total_fare: float
    vehicle_type: str
    currency: str
    # Signed price lock — hand it back to /rides/request so the fare charged
    # is the fare shown. See utils/fare_quote.py.
    quote: Optional[str] = None


class RequestRideIn(Schema):
    current_location: str
    destination: str
    recipient_phone_number: str
    # Locks in the intended method upfront so the driver sees it on the
    # nearby-rides list — the actual payment still happens through the
    # existing pay-cash/pay-online endpoints once the ride completes.
    payment_method: Optional[str] = None
    fare_quote: Optional[str] = None
    vehicle_type: VehicleType = "Bike"


class RequestRideOut(Schema):
    ride_id: int
    status: str
    fare: float
    distance_km: float
    duration_min: float


class NearbyRideOut(Schema):
    id: int
    current_location: str
    destination: str
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    total_fare: Optional[float] = None
    vehicle_type: str
    distance_from_driver: Optional[float] = None
    estimated_pickup_time: Optional[int] = None
    requested_at: datetime
    passenger_name: str
    passenger_phone: str
    passenger_rating: float


class LocationIn(Schema):
    latitude: float
    longitude: float
    address: Optional[str] = None


class DriverInfoOut(Schema):
    id: int
    name: str
    phone: str
    car_model: str
    license_plate: str
    rating: float
    photo: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ActiveRideOut(Schema):
    ride_id: int
    status: str
    requested_at: datetime
    current_location: str
    destination: str
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    total_fare: Optional[float] = None
    payment_status: str
    payment_method: str
    driver: Optional[DriverInfoOut] = None
    # Only set while status == "accepted" (driver heading to the pickup point).
    pickup_eta_min: Optional[int] = None
    driver_distance_km: Optional[float] = None
    # A no-login link the sender can forward to whoever's actually
    # receiving the package — see utils/tracking_token.py.
    tracking_url: Optional[str] = None


class TrackingOut(Schema):
    """Public, unauthenticated — deliberately excludes anything about the
    sender (name, phone, email) or payment. A recipient following this link
    only ever needs to know where their package is and when it's arriving."""
    status: str
    destination: str
    vehicle_type: str
    driver_name: Optional[str] = None
    driver_photo: Optional[str] = None
    driver_latitude: Optional[float] = None
    driver_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    pickup_eta_min: Optional[int] = None


class PaymentCallbackOut(Schema):
    ride_id: int
    payment_status: str
    total_fare: Optional[float] = None
    paid_at: Optional[datetime] = None
    wallet_credit_applied: Optional[float] = None


class ReportNonPaymentIn(Schema):
    reason: str = ""


class DisputeResponseIn(Schema):
    statement: str


class AvailabilityIn(Schema):
    is_online: bool


class AvailabilityOut(Schema):
    is_online: bool
    is_busy: bool


class PassengerInfoOut(Schema):
    name: str
    phone: str
    rating: float
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class DriverActiveRideOut(Schema):
    ride_id: int
    status: str
    current_location: str
    destination: str
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    total_fare: Optional[float] = None
    payment_status: str
    payment_method: str
    # Only set while status == "accepted" (heading to the pickup point).
    pickup_eta_min: Optional[int] = None
    pickup_distance_km: Optional[float] = None
    passenger: PassengerInfoOut


class ConfirmCashIn(Schema):
    code: str


class DriverSummaryOut(Schema):
    completed_trips: int
    completion_rate: float
    todays_earnings: float
    total_earnings: float
    cash_debt: float
    cash_debt_blocked: bool
    is_flagged: bool
    # Card-ride earnings not yet paid out (weekly or instant) — see
    # payout_service.get_driver_wallet_balance.
    wallet_balance: float


class RateRideIn(Schema):
    stars: int
    comment: str = ""


class PayoutOut(Schema):
    id: int
    ride_id: int
    amount: float
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None


class ReferralOut(Schema):
    full_name: str
    joined_at: datetime
    reward_earned: bool


class ReferralSummaryOut(Schema):
    referral_code: str
    wallet_credit_balance: float
    referral_reward_amount: float
    referrals: list[ReferralOut]
