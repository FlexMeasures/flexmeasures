#!/usr/bin/env python3

"""
Quick script to compare clear-sky irradiation computations
from three different libraries.

There might be errors or misunderstandings still in here.
"""


import numpy as np
from solarpy import irradiance_on_plane, standard2solar_time
from pvlib import location
from datetime import datetime
import pytz
from pandas import DatetimeIndex
from tzwhere import tzwhere

from flexmeasures.utils.geo_utils import compute_radiation


tzwhere = tzwhere.tzwhere()

locations = dict(
    Amsterdam=(52.370216, 4.895168),
    Tokyo=(35.6684415, 139.6007844),
    Dallas=(32.779167, -96.808891),
)
datetimes = [datetime(2021, 2, 10, i, tzinfo=pytz.utc) for i in range(24)]
timezones = {k: tzwhere.tzNameAt(*v) for k, v in locations.items()}


def solarpy(latitude: float, longitude: float, dt: datetime, z: str) -> float:
    vnorm = np.array([0, 0, -1])  # plane pointing zenith
    h = 0  # sea-level
    dt = dt.astimezone(pytz.timezone(z)).replace(tzinfo=None)  # local time
    dt = standard2solar_time(dt, longitude)  # solar time
    return irradiance_on_plane(vnorm, h, dt, latitude)


def pysolar(latitude: float, longitude: float, dt: datetime) -> float:
    return compute_radiation(latitude, longitude, dt, cloud_coverage_in_percent=0)


def pvlib(latitude: float, longitude: float, dt: datetime) -> float:
    """
    https://firstgreenconsulting.wordpress.com/2012/04/26/differentiate-between-the-dni-dhi-and-ghi/
    """
    site = location.Location(lat, lon, tz=pytz.utc)
    return site.get_clearsky(DatetimeIndex([dt])).loc[dt]["ghi"]


if __name__ == "__main__":
    for city in locations:
        lat, lon = locations[city]
        timezone = timezones[city]
        for dt in datetimes:
            irrad_pysolar = pysolar(lat, lon, dt)
            irrad_solarpy = solarpy(lat, lon, dt, timezone)
            irrad_pvlib = pvlib(lat, lon, dt)
            print(
                f"For {city} at {dt} UTC ― pysolar: {irrad_pysolar:.2f}, solarpy: {irrad_solarpy:.2f}, pvlib: {irrad_pvlib:.2f}"
            )
