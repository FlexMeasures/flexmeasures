from typing import Optional
from datetime import timedelta
from isodate import duration_isoformat, parse_duration, parse_datetime

import pandas as pd
import timely_beliefs as tb

from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.v1_1.tests.utils import (
    message_for_post_price_data as v1_1_message_for_post_price_data,
)


def get_asset_post_data() -> dict:
    post_data = {
        "name": "Test battery 2",
        "unit": "MW",
        "capacity_in_mw": 3,
        "event_resolution": timedelta(minutes=10).seconds / 60,
        "latitude": 30.1,
        "longitude": 100.42,
        "asset_type_name": "battery",
        "owner_id": find_user_by_email("test_prosumer_user@seita.nl").id,
        "market_id": Sensor.query.filter_by(name="epex_da").one_or_none().id,
    }
    return post_data


def message_for_post_price_data(
    market_id: int,
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
    message["market"] = f"ea1.2018-06.localhost:fm1.{market_id}"
    message["horizon"] = duration_isoformat(timedelta(hours=0))
    if no_horizon or prior_instead_of_horizon:
        message.pop("horizon", None)
    if prior_instead_of_horizon:
        message["prior"] = "2021-01-05T12:00:00+01:00"
    return message


def verify_sensor_data_in_db(
    post_message,
    values,
    db,
    entity_type: str,
    fm_scheme: str,
    swapped_sign: bool = False,
):
    """util method to verify that sensor data ended up in the database"""
    start = parse_datetime(post_message["start"])
    end = start + parse_duration(post_message["duration"])
    sensor: Sensor = SensorField(entity_type, fm_scheme).deserialize(
        post_message[entity_type]
    )
    resolution = sensor.event_resolution
    query = (
        db.session.query(
            TimedBelief.event_start,
            TimedBelief.event_value,
            TimedBelief.belief_horizon,
        )
        .filter(
            (TimedBelief.event_start > start - resolution)
            & (TimedBelief.event_start < end)
        )
        # .filter(TimedBelief.belief_horizon == (TimedBelief.event_start + resolution) - prior)  # only for sensors with 0-hour ex_post knowledge horizon function
        .join(Sensor)
        .filter(Sensor.name == sensor.name)
    )
    if "horizon" in post_message:
        horizon = parse_duration(post_message["horizon"])
        query = query.filter(TimedBelief.belief_horizon == horizon)
    # todo: after basing sensor data on TimedBelief, we should be able to get a BeliefsDataFrame from the query directly
    df = pd.DataFrame(
        query.all(), columns=[col["name"] for col in query.column_descriptions]
    )
    bdf = tb.BeliefsDataFrame(df, sensor=sensor, source="Some source")
    if "prior" in post_message:
        prior = parse_datetime(post_message["prior"])
        bdf = bdf.fixed_viewpoint(prior)
    if swapped_sign:
        bdf["event_value"] = -bdf["event_value"]
    assert bdf["event_value"].tolist() == values


def message_for_post_prognosis(fm_scheme: str = "fm1"):
    """
    Posting prognosis for a wind turbine's production.
    """
    message = {
        "type": "PostPrognosisRequest",
        "connection": f"ea1.2018-06.localhost:{fm_scheme}.2",
        "values": [-300, -300, -300, 0, 0, -300],
        "start": "2021-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "prior": "2020-12-31T18:00:00Z",
        "unit": "MW",
    }
    return message
