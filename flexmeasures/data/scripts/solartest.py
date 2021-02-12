#!/usr/bin/env python3

"""
Quick script to compare clear-sky irradiation computations
from three different libraries.

There might be errors or misunderstandings still in here.
"""


from solarpy import irradiance_on_plane, solar_vector_ned, standard2solar_time
from pvlib import location
from datetime import datetime, timedelta
import matplotlib.dates as mpl_dates
import matplotlib.pyplot as plt
import pytz
from pandas import DatetimeIndex
from tzwhere import tzwhere

from flexmeasures.utils.geo_utils import compute_radiation


tzwhere = tzwhere.tzwhere()

locations = {
    "Amsterdam": (52.370216, 4.895168),
    "Tokyo": (35.6684415, 139.6007844),
    "Dallas": (32.779167, -96.808891),
    "Cape-Town": (-33.943707, 18.588740),  # check southern hemisphere, too
}
datetimes = [
    datetime(2021, 2, 10, tzinfo=pytz.utc) + timedelta(minutes=i * 20)
    for i in range(24 * 3)
]
timezones = {k: tzwhere.tzNameAt(*v) for k, v in locations.items()}


def solarpy(latitude: float, longitude: float, dt: datetime, z: str) -> float:
    h = 0  # sea-level
    dt = dt.astimezone(pytz.timezone(z)).replace(tzinfo=None)  # local time
    dt = standard2solar_time(dt, longitude)  # solar time
    vnorm = solar_vector_ned(
        dt, latitude
    )  # plane pointing directly to the sun -> for clear sky irradiance
    vnorm[-1] = vnorm[-1] * 0.99999  # avoid floating point error
    return irradiance_on_plane(vnorm, h, dt, latitude)


def pysolar(latitude: float, longitude: float, dt: datetime) -> float:
    return compute_radiation(latitude, longitude, dt, cloud_coverage_in_percent=0)


def pvlib(latitude: float, longitude: float, dt: datetime) -> float:
    """
    https://firstgreenconsulting.wordpress.com/2012/04/26/differentiate-between-the-dni-dhi-and-ghi/
    """
    site = location.Location(latitude, longitude, tz=pytz.utc)
    return site.get_clearsky(DatetimeIndex([dt])).loc[dt]["ghi"]


def plot_irradiation(city, datetimes, values):
    date_ticks = mpl_dates.date2num(datetimes)
    # matplotlib.pyplot.plot_date(date_ticks, values)

    fig, ax = plt.subplots()

    for lib in ("pysolar", "solarpy", "pvlib"):
        ax.plot(date_ticks, values[lib], label=lib)

    ax.set(
        xlabel="Time (20m)",
        ylabel="irradiation (?)",
        title=f"Irradiation for {city} on 10 Feb 2021",
    )
    ax.grid()

    plt.legend()

    fig.savefig(f"test-irradiation-{city}.png")
    plt.show()


if __name__ == "__main__":
    for city in locations:
        values = dict(pysolar=[], solarpy=[], pvlib=[])
        lat, lon = locations[city]
        timezone = timezones[city]
        for dt in datetimes:
            irrad_pysolar = pysolar(lat, lon, dt)
            values["pysolar"].append(irrad_pysolar)
            irrad_solarpy = solarpy(lat, lon, dt, timezone)
            values["solarpy"].append(irrad_solarpy)
            irrad_pvlib = pvlib(lat, lon, dt)
            values["pvlib"].append(irrad_pvlib)
            print(
                f"For {city} at {dt} UTC ― pysolar: {irrad_pysolar:.2f}, solarpy: {irrad_solarpy:.2f}, pvlib: {irrad_pvlib:.2f}"
            )
        plot_irradiation(city, datetimes, values)
