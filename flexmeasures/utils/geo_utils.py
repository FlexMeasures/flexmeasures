from __future__ import annotations

import math


def cos_rad_lat(latitude: float) -> float:
    return math.cos(math.radians(latitude))


def sin_rad_lat(latitude: float) -> float:
    return math.sin(math.radians(latitude))


def rad_lng(longitude: float) -> float:
    return math.radians(longitude)


def earth_distance(
    location: tuple[float, float], other_location: tuple[float, float]
) -> float:
    """Great circle distance in km between two locations on Earth."""
    r = 6371  # Radius of Earth in kilometres
    _cos_rad_lat = cos_rad_lat(location[0])
    _sin_rad_lat = sin_rad_lat(location[0])
    _rad_lng = rad_lng(location[1])
    other_cos_rad_lat = cos_rad_lat(other_location[0])
    other_sin_rad_lat = sin_rad_lat(other_location[0])
    other_rad_lng = rad_lng(other_location[1])
    return (
        math.acos(
            _cos_rad_lat * other_cos_rad_lat * math.cos(_rad_lng - other_rad_lng)
            + _sin_rad_lat * other_sin_rad_lat
        )
        * r
    )


def parse_lat_lng(kwargs) -> tuple[float, float] | tuple[None, None]:
    """Parses latitude and longitude values stated in kwargs.

    Can be called with an object that has latitude and longitude properties, for example:

        lat, lng = parse_lat_lng(object=asset)

    Can also be called with latitude and longitude parameters, for example:

        lat, lng = parse_lat_lng(latitude=32, longitude=54)
        lat, lng = parse_lat_lng(lat=32, lng=54)

    """
    if kwargs is not None:
        if all(k in kwargs for k in ("latitude", "longitude")):
            return kwargs["latitude"], kwargs["longitude"]
        elif all(k in kwargs for k in ("lat", "lng")):
            return kwargs["lat"], kwargs["lng"]
        elif "object" in kwargs:
            obj = kwargs["object"]
            if hasattr(obj, "latitude") and hasattr(obj, "longitude"):
                return obj.latitude, obj.longitude
            elif hasattr(obj, "lat") and hasattr(obj, "lng"):
                return obj.lat, obj.lng
            elif hasattr(obj, "location"):
                return obj.location
    return None, None
