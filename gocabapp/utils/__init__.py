import json, datetime, decimal
from uuid import UUID

class DjangoSafeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):      return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)): return obj.isoformat()
        if isinstance(obj, UUID):                 return str(obj)
        return super().default(obj)

from .fare_pricing import calculate_ride_fare, estimate_pickup_time
from .distance_utils import (
    route_with_coords,
    get_nearby_rides,
    detect_city,
    city_limits,
    google_distance,
    haversine_km,
)

__all__ = [
    "calculate_ride_fare",
    "estimate_pickup_time",
    "route_with_coords",
    "get_nearby_rides",
    "detect_city",
    "city_limits",
    "google_distance",
    "haversine_km",
]