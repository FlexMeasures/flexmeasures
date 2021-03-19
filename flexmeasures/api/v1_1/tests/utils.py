"""Useful test messages"""
from typing import Optional, Dict, Any
from datetime import timedelta
from isodate import duration_isoformat, parse_duration, parse_datetime

import pandas as pd
from numpy import tile

from flexmeasures.api.common.utils.api_utils import get_generic_asset
from flexmeasures.data.models.markets import Market, Price


def message_for_get_prognosis(
    invalid_horizon=False,
    rolling_horizon=False,
    with_prior=False,
    no_data=False,
    no_resolution=False,
    single_connection=False,
    timezone_alternative=False,
) -> dict:
    message = {
        "type": "GetPrognosisRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "horizon": "PT6H",
        "resolution": "PT15M",
        "connections": ["CS 1", "CS 2", "CS 3"],
        "unit": "MW",
    }
    if invalid_horizon:
        message["horizon"] = "T6H"
    elif rolling_horizon:
        message[
            "horizon"
        ] = "R/PT6H"  # with or without R/ shouldn't matter: both are interpreted as rolling horizons
    if with_prior:
        message["prior"] = ("2015-03-01T00:00:00Z",)
    if no_data:
        message["start"] = ("2010-01-01T00:00:00Z",)
    if no_resolution:
        message.pop("resolution", None)
    if single_connection:
        message["connection"] = message["connections"][0]
        message.pop("connections", None)
    if timezone_alternative:
        message["start"] = ("2015-01-01T00:00:00+00:00",)
    return message


def message_for_post_price_data(
    tile_n: int = 1,
    compress_n: int = 1,
    duration: Optional[timedelta] = None,
    invalid_unit: bool = False,
) -> dict:
    """
    The default message has 24 hourly values.

    :param tile_n:       Tile the price profile back to back to obtain price data for n days (default = 1).
    :param compress_n:   Compress the price profile to obtain price data with a coarser resolution (default = 1),
                         e.g. compress=4 leads to a resolution of 4 hours.
    :param duration:     Set a duration explicitly to obtain price data with a coarser or finer resolution
                         (the default is equal to 24 hours * tile_n),
                         e.g. (assuming tile_n=1) duration=timedelta(hours=6) leads to a resolution of 15 minutes,
                         and duration=timedelta(hours=48) leads to a resolution of 2 hours.
    :param invalid_unit: Choose an invalid unit for the test market (epex_da).
    """
    message = {
        "type": "PostPriceDataRequest",
        "market": "ea1.2018-06.localhost:epex_da",
        "values": tile(
            [
                52.37,
                51.14,
                49.09,
                48.35,
                48.47,
                49.98,
                58.7,
                67.76,
                69.21,
                70.26,
                70.46,
                70,
                70.7,
                70.41,
                70,
                64.53,
                65.92,
                69.72,
                70.51,
                75.49,
                70.35,
                70.01,
                66.98,
                58.61,
            ],
            tile_n,
        ).tolist(),
        "start": "2021-01-06T00:00:00+01:00",
        "duration": duration_isoformat(timedelta(hours=24 * tile_n)),
        "horizon": duration_isoformat(timedelta(hours=11 + 24 * tile_n)),
        "unit": "EUR/MWh",
    }
    if duration is not None:
        message["duration"] = duration
    if compress_n > 1:
        message["values"] = message["values"][::compress_n]
    if invalid_unit:
        message["unit"] = "KRW/kWh"  # That is, an invalid unit for EPEX SPOT.
    return message


def message_for_post_weather_data(
    invalid_unit: bool = False, temperature: bool = False
) -> dict:
    message: Dict[str, Any] = {
        "type": "PostWeatherDataRequest",
        "groups": [
            {
                "sensor": "ea1.2018-06.localhost:wind_speed:33.4843866:126",
                "values": [20.04, 20.23, 20.41, 20.51, 20.55, 20.57],
            }
        ],
        "start": "2015-01-01T15:00:00+09:00",
        "duration": "PT30M",
        "horizon": "PT3H",
        "unit": "m/s",
    }
    if temperature:
        message["groups"][0][
            "sensor"
        ] = "ea1.2018-06.localhost:temperature:33.4843866:126"
        if not invalid_unit:
            message["unit"] = "°C"  # Right unit for temperature
    elif invalid_unit:
        message["unit"] = "°C"  # Wrong unit for wind speed
    return message


def verify_prices_in_db(post_message, values, db, swapped_sign: bool = False):
    """util method to verify that price data ended up in the database"""
    start = parse_datetime(post_message["start"])
    end = start + parse_duration(post_message["duration"])
    horizon = parse_duration(post_message["horizon"])
    market: Market = get_generic_asset(post_message["market"], "market")
    resolution = market.event_resolution
    query = (
        db.session.query(Price.value, Price.horizon)
        .filter((Price.datetime > start - resolution) & (Price.datetime < end))
        .filter(Price.horizon == horizon - (end - (Price.datetime + resolution)))
        .join(Market)
        .filter(Market.name == market.name)
    )
    df = pd.DataFrame(
        query.all(), columns=[col["name"] for col in query.column_descriptions]
    )
    if swapped_sign:
        df["value"] = -df["value"]
    assert df.value.tolist() == values
