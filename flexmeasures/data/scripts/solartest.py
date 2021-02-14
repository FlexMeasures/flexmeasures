#!/usr/bin/env python3

"""
Quick script to compare clear-sky irradiance computations
from three different libraries.
"""
from typing import List, Dict
from datetime import datetime, timedelta

import solarpy
import pvlib
import pysolar
import matplotlib.dates as mpl_dates
import matplotlib.pyplot as plt
import pytz
from pandas import DatetimeIndex
from tzwhere import tzwhere
from astral import LocationInfo
from astral.sun import sun


DAY = datetime(2021, 2, 10, tzinfo=pytz.utc)
tzwhere = tzwhere.tzwhere()

locations = {
    "Amsterdam": (52.370216, 4.895168),
    "Tokyo": (35.6684415, 139.6007844),
    "Dallas": (32.779167, -96.808891),
    "Cape-Town": (-33.943707, 18.588740),  # check southern hemisphere, too
}
datetimes = [DAY + timedelta(minutes=i * 20) for i in range(24 * 3)]
timezones = {k: tzwhere.tzNameAt(*v) for k, v in locations.items()}


def irradiance_by_solarpy(
    latitude: float, longitude: float, dt: datetime, z: str, metric: str = "dni"
) -> float:
    """Supports direct horizontal irradiance and direct normal irradiance."""
    h = 0  # sea-level
    dt = dt.astimezone(pytz.timezone(z)).replace(tzinfo=None)  # local time
    dt = solarpy.standard2solar_time(dt, longitude)  # solar time
    if metric == "dhi":  # direct horizontal irradiance
        vnorm = [0, 0, -1]  # plane pointing up
    elif metric == "dni":  # direct normal irradiance
        vnorm = solarpy.solar_vector_ned(
            dt, latitude
        )  # plane pointing directly to the sun
        vnorm[-1] = vnorm[-1] * 0.99999  # avoid floating point error
    else:
        return NotImplemented
    return solarpy.irradiance_on_plane(vnorm, h, dt, latitude)


def irradiance_by_pysolar(
    latitude: float, longitude: float, dt: datetime, method: str = "dni"
) -> float:
    """Supports direct normal irradiance."""
    altitude_deg = pysolar.solar.get_altitude(latitude, longitude, dt)
    if method == "dni":
        return pysolar.radiation.get_radiation_direct(dt, altitude_deg)
    else:
        return NotImplemented


def irradiance_by_pvlib(
    latitude: float, longitude: float, dt: datetime, method: str = "dni"
) -> float:
    """
    Supports direct horizontal irradiance, direct normal irradiance and global horizontal irradiance.
    https://firstgreenconsulting.wordpress.com/2012/04/26/differentiate-between-the-dni-dhi-and-ghi/
    """
    site = pvlib.location.Location(latitude, longitude, tz=pytz.utc)
    solpos = site.get_solarposition(DatetimeIndex([dt]))
    irradiance = site.get_clearsky(DatetimeIndex([dt]), solar_position=solpos).loc[dt]
    if method in ("ghi", "dni", "dhi"):
        return irradiance[method]
    else:
        return NotImplemented


def plot_irradiance(
    city: str,
    datetimes: List[datetime],
    values: Dict[str, List[float]],
    sun_times: Dict[str, datetime],
):

    fig, ax = plt.subplots()

    ax.set(
        xlabel="Time (20m)",
        ylabel="Direct Normal Irradiance (W/m²)",
        title=f"Irradiance for {city} on {DAY.date()}",
    )

    # draw values
    date_ticks = mpl_dates.date2num(datetimes)
    for lib in ("pysolar", "solarpy", "pvlib"):
        plt.plot_date(date_ticks, values[lib], "-", label=lib)

    # make date ticks look okay
    plt.gca().xaxis.set_major_locator(mpl_dates.HourLocator())
    plt.setp(plt.gca().xaxis.get_majorticklabels(), "rotation", 40)

    # draw day phases boxes
    dawn_tick, sunrise_tick, noon_tick, sunset_tick, dusk_tick = mpl_dates.date2num(
        (
            sun_times["dawn"],
            sun_times["sunrise"],
            sun_times["noon"],
            sun_times["sunset"],
            sun_times["dusk"],
        )
    )
    dawn_to_sunrise = plt.Rectangle(
        (dawn_tick, -100),
        sunrise_tick - dawn_tick,
        1100,
        fc="floralwhite",
        ec="lemonchiffon",
        label="Dawn to Sunrise",
    )
    plt.gca().add_patch(dawn_to_sunrise)

    sunrise_to_sunset = plt.Rectangle(
        (sunrise_tick, -100),
        sunset_tick - sunrise_tick,
        1100,
        fc="lightyellow",
        ec="lemonchiffon",
        label="Sunrise to sunset",
    )
    plt.gca().add_patch(sunrise_to_sunset)

    sunset_to_dusk = plt.Rectangle(
        (sunset_tick, -100),
        dusk_tick - sunset_tick,
        1100,
        fc="oldlace",
        ec="lemonchiffon",
        label="Sunset to dusk",
    )
    plt.gca().add_patch(sunset_to_dusk)

    # draw noon
    plt.axvline(x=noon_tick, color="gold", label="Noon")

    plt.legend()

    fig.savefig(f"test-irradiance-{city}.png")
    plt.show()


if __name__ == "__main__":
    for city in locations:
        values = dict(pysolar=[], solarpy=[], pvlib=[])
        lat, lon = locations[city]
        timezone = timezones[city]
        loc_info = LocationInfo(timezone=timezone, latitude=lat, longitude=lon)
        # this gives 'dawn', 'sunrise', 'noon', 'sunset' and 'dusk'
        sun_times = sun(loc_info.observer, date=DAY.date(), tzinfo=loc_info.timezone)
        local_datetimes = [
            dt.replace(tzinfo=pytz.timezone(timezones[city])) for dt in datetimes
        ]

        for dt in local_datetimes:
            irrad_pysolar = irradiance_by_pysolar(lat, lon, dt)
            values["pysolar"].append(irrad_pysolar)
            irrad_solarpy = irradiance_by_solarpy(lat, lon, dt, timezone)
            values["solarpy"].append(irrad_solarpy)
            irrad_pvlib = irradiance_by_pvlib(lat, lon, dt)
            values["pvlib"].append(irrad_pvlib)
            print(
                f"For {city} at {dt} {timezones[city]} ― pysolar: {irrad_pysolar:.2f}, solarpy: {irrad_solarpy:.2f}, pvlib: {irrad_pvlib:.2f}"
            )
        plot_irradiance(city, local_datetimes, values, sun_times)
