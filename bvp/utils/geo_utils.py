from typing import Tuple, Union
from datetime import datetime

from pysolar.solar import get_altitude
from pysolar.radiation import get_radiation_direct


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


def find_closest_weather_sensor(sensor_type: str, **kwargs):
    """Returns the closest weather sensor of a given type. Parses latitude and longitude values stated in kwargs.

    Can be called with an object that has latitude and longitude properties, for example:

        sensor = find_closest_weather_sensor("wind_speed", object=asset)

    Can also be called with latitude and longitude parameters, for example:

        sensor = find_closest_weather_sensor("temperature", latitude=32, longitude=54)
        sensor = find_closest_weather_sensor("temperature", lat=32, lng=54)

    """
    from bvp.data.models.weather import WeatherSensor

    latitude, longitude = parse_lat_lng(kwargs)
    return (
        WeatherSensor.query.filter(
            WeatherSensor.weather_sensor_type_name == sensor_type
        )
        .order_by(
            WeatherSensor.great_circle_distance(lat=latitude, lng=longitude).asc()
        )
        .first()
    )


def compute_radiation(
    latitude: float, longitude: float, dt: datetime, cloud_coverage_in_percent: int
) -> float:
    """Compute the radiation received on a location at a specific time.
    This uses pysolar to compute clear-sky radiation and adjusts this for cloud coverage,
    using an algorithm described at http://www.shodor.org/os411/courses/_master/tools/calculators/solarrad/
    """
    altitude_deg = get_altitude(latitude, longitude, dt)

    # pysolar's get_radiation_direct is not smart enough to return zeros at night.
    if altitude_deg <= 0:
        return 0

    radiation_clear_sky = get_radiation_direct(dt, altitude_deg)

    return radiation_clear_sky * (1 - .75 * (cloud_coverage_in_percent / 100) ** 3.4)
