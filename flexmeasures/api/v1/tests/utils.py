"""Useful test messages"""
from datetime import timedelta
from typing import List, Optional, Union

from isodate import duration_isoformat, parse_datetime, parse_duration
from numpy import tile
import pandas as pd

from flexmeasures.api.common.utils.validators import validate_user_sources
from flexmeasures.data.models.assets import Power, Asset


def message_for_get_meter_data(
    no_connection: bool = False,
    invalid_connection: bool = False,
    single_connection: bool = False,
    demo_connection: bool = False,
    invalid_unit: bool = False,
    no_unit: bool = False,
    resolution: str = "",
    source: Optional[Union[str, List[str]]] = None,
) -> dict:
    message = {
        "type": "GetMeterDataRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "connections": ["CS 1", "CS 2", "CS 3"],
        "unit": "MW",
    }
    if no_connection:
        message.pop("connections", None)
    elif invalid_connection:
        message["connections"] = ["Non-existing asset 1", "Non-existing asset 2"]
    elif single_connection:
        message["connection"] = message["connections"][0]
        message.pop("connections", None)
    elif demo_connection:
        message["connection"] = "CS 0"
        message.pop("connections", None)
    if no_unit:
        message.pop("unit", None)
    elif invalid_unit:
        message["unit"] = "MW/h"
    if resolution:
        message["resolution"] = resolution
    if source:
        message["source"] = source
    return message


def message_for_post_meter_data(
    no_connection: bool = False,
    single_connection: bool = False,
    single_connection_group: bool = False,
    production: bool = False,
    different_target_resolutions: bool = False,
    tile_n=1,
) -> dict:
    sign = 1 if production is False else -1
    message = {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connections": ["CS 1", "CS 2"],
                "values": (
                    tile([306.66, 306.66, 0, 0, 306.66, 306.66], tile_n) * sign
                ).tolist(),
            },
            {
                "connection": ["CS 4" if different_target_resolutions else "CS 3"],
                "values": (
                    tile([306.66, 0, 0, 0, 306.66, 306.66], tile_n) * sign
                ).tolist(),
            },
        ],
        "start": "2015-01-01T00:00:00Z",
        "duration": duration_isoformat(timedelta(hours=1.5 * tile_n)),
        "horizon": "PT0H",
        "unit": "MW",
    }
    if no_connection:
        message.pop("groups", None)
    elif single_connection:
        message["connection"] = message["groups"][0]["connections"][0]
        message["values"] = message["groups"][1]["values"]
        message.pop("groups", None)
    elif single_connection_group:
        message["connections"] = message["groups"][0]["connections"]
        message["values"] = message["groups"][0]["values"]
        message.pop("groups", None)

    return message


def count_connections_in_post_message(message: dict) -> int:
    connections = 0
    if "groups" in message:
        message = dict(
            connections=message["groups"][0]["connections"],
            connection=message["groups"][1]["connection"],
        )
    if "connection" in message:
        connections += 1
    if "connections" in message:
        connections += len(message["connections"])
    return connections


def verify_power_in_db(
    message, asset, expected_df: pd.DataFrame, db, swapped_sign: bool = False
):
    """util method to verify that power data ended up in the database"""
    # todo: combine with verify_prices_in_db (in v1_1 utils) into a single function (NB different horizon filters)
    start = parse_datetime(message["start"])
    end = start + parse_duration(message["duration"])
    horizon = (
        parse_duration(message["horizon"]) if "horizon" in message else timedelta(0)
    )
    resolution = asset.event_resolution
    query = (
        db.session.query(Power.datetime, Power.value, Power.data_source_id)
        .filter((Power.datetime > start - resolution) & (Power.datetime < end))
        .filter(Power.horizon == horizon)
        .join(Asset)
        .filter(Asset.name == asset.name)
    )
    if "source" in message:
        source_ids = validate_user_sources(message["source"])
        query = query.filter(Power.data_source_id.in_(source_ids))
    df = pd.DataFrame(
        query.all(), columns=[col["name"] for col in query.column_descriptions]
    )
    df = df.set_index(["datetime", "data_source_id"]).sort_index()
    if swapped_sign:
        df["value"] = -df["value"]

    assert df["value"].to_list() == expected_df["value"].to_list()
