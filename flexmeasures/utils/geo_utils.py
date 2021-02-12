from typing import Tuple, Union
from datetime import datetime

from pvlib.location import Location
from pvlib.forecast import ForecastModel
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


def compute_radiation(
    latitude: float, longitude: float, dt: datetime, cloud_coverage_in_percent: int
) -> float:
    """Compute the radiation received on a location at a specific time.
    This uses pvlib to
    1) compute clear-sky radiation as Global Horizontal Irradiance (GHI),
       which includes both Direct Normal Irradiance (DNI)
       and Diffuse Horizontal Irradiance (DHI).
    2) adjust the GHI for cloud coverage, using an algorithm described in
       Larson et. al. "Day-ahead forecasting of solar power output from
         photovoltaic plants in the American Southwest" Renewable Energy
         91, 11-20 (2016).
    """
    site = Location(latitude, longitude, tz=dt.tzinfo)
    solpos = site.get_solarposition(pd.DatetimeIndex([dt]))
    ghi = site.get_clearsky(pd.DatetimeIndex([dt]), solar_position=solpos).loc[dt][
        "ghi"
    ]
    return ForecastModel.cloud_cover_to_ghi_linear(None, cloud_coverage_in_percent, ghi)
