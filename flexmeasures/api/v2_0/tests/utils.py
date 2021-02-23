from flexmeasures.data.services.users import find_user_by_email
from typing import Optional
from datetime import timedelta
from isodate import duration_isoformat, parse_duration, parse_datetime

import pandas as pd
from numpy import tile
import timely_beliefs as tb

from flexmeasures.data.models.markets import Market, Price
from flexmeasures.api.v1_1.tests.utils import get_market


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
    invalid_unit: bool = False,
    tile_n: int = 1,
    compress_n: int = 1,
    duration: Optional[timedelta] = None,
    no_horizon: bool = False,
    prior_instead_of_horizon: bool = False,
) -> dict:
    """
    The default message has 24 hourly values.

    :param tile_n: Tile the price profile back to back to obtain price data for n days (default = 1).
    :param compress_n: Compress the price profile to obtain price data with a coarser resolution (default = 1),
                       e.g. compress=4 leads to a resolution of 4 hours.
    :param duration: Set a duration explicitly to obtain price data with a coarser or finer resolution (default is equal to 24 hours * tile_n),
                     e.g. (assuming tile_n=1) duration=timedelta(hours=6) leads to a resolution of 15 minutes,
                     and duration=timedelta(hours=48) leads to a resolution of 2 hours.
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
        "horizon": duration_isoformat(timedelta(hours=0)),
        "unit": "EUR/MWh",
    }
    if duration is not None:
        message["duration"] = duration
    if compress_n > 1:
        message["values"] = message["values"][::compress_n]
    if invalid_unit:
        message["unit"] = "KRW/kWh"  # That is, an invalid unit for EPEX SPOT.
    if no_horizon or prior_instead_of_horizon:
        message.pop("horizon", None)
    if prior_instead_of_horizon:
        message["prior"] = "2021-01-05T12:00:00+01:00"
    return message


def verify_prices_in_db(post_message, values, db, swapped_sign: bool = False):
    """util method to verify that price data ended up in the database"""
    start = parse_datetime(post_message["start"])
    end = start + parse_duration(post_message["duration"])
    market: Market = get_market(post_message)
    resolution = market.event_resolution
    if "horizon" in post_message:
        horizon = parse_duration(post_message["horizon"])
        query = (
            db.session.query(Price.datetime, Price.value, Price.horizon)
            .filter((Price.datetime > start - resolution) & (Price.datetime < end))
            .filter(Price.horizon == horizon)
            .join(Market)
            .filter(Market.name == market.name)
        )
    else:
        query = (
            db.session.query(
                Price.datetime,
                Price.value,
                Price.horizon,
            )
            .filter((Price.datetime > start - resolution) & (Price.datetime < end))
            # .filter(Price.horizon == (Price.datetime + resolution) - prior)  # only for sensors with 0-hour ex_post knowledge horizon function
            .join(Market)
            .filter(Market.name == market.name)
        )
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
