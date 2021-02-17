from typing import Tuple, Union
from datetime import datetime

from pvlib.location import Location
import pandas as pd


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


def compute_irradiance(
    latitude: float, longitude: float, dt: datetime, cloud_coverage: float
) -> float:
    """Compute the irradiance received on a location at a specific time.
    This uses pvlib to
    1)  compute clear-sky irradiance as Global Horizontal Irradiance (GHI),
        which includes both Direct Normal Irradiance (DNI)
        and Diffuse Horizontal Irradiance (DHI).
    2)  adjust the GHI for cloud coverage
    """
    site = Location(latitude, longitude, tz=dt.tzinfo)
    solpos = site.get_solarposition(pd.DatetimeIndex([dt]))
    ghi_clear = site.get_clearsky(pd.DatetimeIndex([dt]), solar_position=solpos).loc[
        dt
    ]["ghi"]
    return ghi_clear_to_ghi(ghi_clear, cloud_coverage)


def ghi_clear_to_ghi(ghi_clear: float, cloud_coverage: float) -> float:
    """Compute global horizontal irradiance (GHI) from clear-sky GHI, given a cloud coverage between 0 and 1.

    References
    ----------
    Perez, R., Moore, K., Wilcox, S., Renne, D., Zelenka, A., 2007.
    Forecasting solar radiation – preliminary evaluation of an
    approach based upon the national forecast database. Solar Energy
    81, 809–812.
    """
    if cloud_coverage < 0 or cloud_coverage > 1:
        raise ValueError("cloud_coverage should lie in the interval [0, 1]")
    return (1 - 0.87 * cloud_coverage ** 1.9) * ghi_clear
