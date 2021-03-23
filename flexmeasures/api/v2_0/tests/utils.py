from flexmeasures.data.services.users import find_user_by_email
from typing import Optional
from datetime import timedelta
from isodate import duration_isoformat, parse_duration, parse_datetime

import pandas as pd
import timely_beliefs as tb

from flexmeasures.api.common.utils.api_utils import get_generic_asset
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import WeatherSensor, Weather
from flexmeasures.api.v1_1.tests.utils import (
    message_for_post_price_data as v1_1_message_for_post_price_data,
)


def get_asset_post_data() -> dict:
    post_data = {
        "name": "Test battery 2",
        "unit": "kW",
        "capacity_in_mw": 3,
        "event_resolution": timedelta(minutes=10).seconds / 60,
        "latitude": 30.1,
        "longitude": 100.42,
        "asset_type_name": "battery",
        "owner_id": find_user_by_email("test_prosumer@seita.nl").id,
        "market_id": Market.query.filter_by(name="epex_da").one_or_none().id,
    }
    return post_data


def message_for_post_price_data(
    tile_n: int = 1,
    compress_n: int = 1,
    duration: Optional[timedelta] = None,
    invalid_unit: bool = False,
    no_horizon: bool = False,
    prior_instead_of_horizon: bool = False,
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
    :param no_horizon:   Remove the horizon parameter.
    :param prior_instead_of_horizon: Remove the horizon parameter and replace it with a prior parameter.
    """
    message = v1_1_message_for_post_price_data(
        tile_n=tile_n,
        compress_n=compress_n,
        duration=duration,
        invalid_unit=invalid_unit,
    )
    message["horizon"] = duration_isoformat(timedelta(hours=0))
    if no_horizon or prior_instead_of_horizon:
        message.pop("horizon", None)
    if prior_instead_of_horizon:
        message["prior"] = "2021-01-05T12:00:00+01:00"
    return message


def verify_sensor_data_in_db(
    post_message, values, db, entity_type: str, swapped_sign: bool = False
):
    """util method to verify that sensor data ended up in the database"""
    if entity_type == "connection":
        sensor_type = Asset
        data_type = Power
    elif entity_type == "market":
        sensor_type = Market
        data_type = Price
    elif entity_type == "sensor":
        sensor_type = WeatherSensor
        data_type = Weather
    else:
        raise ValueError("Unknown entity type")

    start = parse_datetime(post_message["start"])
    end = start + parse_duration(post_message["duration"])
    market: Market = get_generic_asset(post_message[entity_type], entity_type)
    resolution = market.event_resolution
    if "horizon" in post_message:
        horizon = parse_duration(post_message["horizon"])
        query = (
            db.session.query(data_type.datetime, data_type.value, data_type.horizon)
            .filter(
                (data_type.datetime > start - resolution) & (data_type.datetime < end)
            )
            .filter(data_type.horizon == horizon)
            .join(sensor_type)
            .filter(sensor_type.name == market.name)
        )
    else:
        query = (
            db.session.query(
                data_type.datetime,
                data_type.value,
                data_type.horizon,
            )
            .filter(
                (data_type.datetime > start - resolution) & (data_type.datetime < end)
            )
            # .filter(data_type.horizon == (data_type.datetime + resolution) - prior)  # only for sensors with 0-hour ex_post knowledge horizon function
            .join(sensor_type)
            .filter(sensor_type.name == market.name)
        )
    # todo: after basing Price on TimedBelief, we should be able to get a BeliefsDataFrame from the query directly
    df = pd.DataFrame(
        query.all(), columns=[col["name"] for col in query.column_descriptions]
    )
    df = df.rename(
        columns={
            "value": "event_value",
            "datetime": "event_start",
            "horizon": "belief_horizon",
        }
    )
    bdf = tb.BeliefsDataFrame(df, sensor=market, source="Some source")
    if "prior" in post_message:
        prior = parse_datetime(post_message["prior"])
        bdf = bdf.fixed_viewpoint(prior)
    if swapped_sign:
        bdf["event_value"] = -bdf["event_value"]
    assert bdf["event_value"].tolist() == values


def message_for_post_prognosis():
    message = {
        "type": "PostPrognosisRequest",
        "connection": "ea1.2018-06.localhost:1:2",
        "values": [300, 300, 300, 0, 0, 300],
        "start": "2021-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "prior": "2020-12-31T18:00:00Z",
        "unit": "MW",
    }
    return message
