from typing import Tuple, Union


def parse_lat_lng(kwargs) -> Union[Tuple[float, float], Tuple[None, None]]:
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
    return None, None
