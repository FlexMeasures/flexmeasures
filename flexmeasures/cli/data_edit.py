from datetime import timedelta
from typing import Union, List, Optional

import click
import pandas as pd
from flask import current_app as app
from flask.cli import with_appcontext

from flexmeasures import Sensor
from flexmeasures.data import db
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db


@click.group("edit")
def fm_edit_data():
    """FlexMeasures: Edit data."""


@fm_edit_data.command("attribute")
@with_appcontext
@click.option(
    "--asset-id",
    "assets",
    required=False,
    multiple=True,
    type=GenericAssetIdField(),
    help="Add/edit attribute to this asset. Follow up with the asset's ID.",
)
@click.option(
    "--sensor-id",
    "sensors",
    required=False,
    multiple=True,
    type=SensorIdField(),
    help="Add/edit attribute to this sensor. Follow up with the sensor's ID.",
)
@click.option(
    "--attribute",
    "attribute_key",
    required=True,
    help="Add/edit this attribute. Follow up with the name of the attribute.",
)
@click.option(
    "--float",
    "attribute_float_value",
    required=False,
    type=float,
    help="Set the attribute to this float value.",
)
@click.option(
    "--bool",
    "attribute_bool_value",
    required=False,
    type=bool,
    help="Set the attribute to this bool value.",
)
@click.option(
    "--str",
    "attribute_str_value",
    required=False,
    type=str,
    help="Set the attribute to this string value.",
)
@click.option(
    "--int",
    "attribute_int_value",
    required=False,
    type=int,
    help="Set the attribute to this integer value.",
)
@click.option(
    "--null",
    "attribute_null_value",
    required=False,
    is_flag=True,
    default=False,
    help="Set the attribute to a null value.",
)
def edit_attribute(
    attribute_key: str,
    assets: List[GenericAsset],
    sensors: List[Sensor],
    attribute_null_value: bool,
    attribute_float_value: Optional[float] = None,
    attribute_bool_value: Optional[bool] = None,
    attribute_str_value: Optional[str] = None,
    attribute_int_value: Optional[int] = None,
):
    """Edit (or add) an asset attribute or sensor attribute."""

    if not assets and not sensors:
        raise ValueError("Missing flag: pass at least one --asset-id or --sensor-id.")

    # Parse attribute value
    attribute_value = parse_attribute_value(
        attribute_float_value=attribute_float_value,
        attribute_bool_value=attribute_bool_value,
        attribute_str_value=attribute_str_value,
        attribute_int_value=attribute_int_value,
        attribute_null_value=attribute_null_value,
    )

    # Set attribute
    for asset in assets:
        asset.attributes[attribute_key] = attribute_value
        db.session.add(asset)
    for sensor in sensors:
        sensor.attributes[attribute_key] = attribute_value
        db.session.add(sensor)
    db.session.commit()
    print("Successfully edited/added attribute.")


@fm_edit_data.command("resample-data")
@with_appcontext
@click.option(
    "--sensor-id",
    "sensor_ids",
    multiple=True,
    required=True,
    help="Resample data for this sensor. Follow up with the sensor's ID. This argument can be given multiple times.",
)
@click.option(
    "--event-resolution",
    "event_resolution_in_minutes",
    type=int,
    required=True,
    help="New event resolution as an integer number of minutes.",
)
@click.option(
    "--from",
    "start_str",
    required=False,
    help="Resample only data from this datetime onwards. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--until",
    "end_str",
    required=False,
    help="Resample only data until this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--skip-integrity-check",
    is_flag=True,
    help="Whether to skip checking the resampled time series data for each sensor."
    " By default, an excerpt and the mean value of the original"
    " and resampled data will be shown for manual approval.",
)
def resample_sensor_data(
    sensor_ids: List[int],
    event_resolution_in_minutes: int,
    start_str: Optional[str] = None,
    end_str: Optional[str] = None,
    skip_integrity_check: bool = False,
):
    """Assign a new event resolution to an existing sensor and resample its data accordingly."""
    event_resolution = timedelta(minutes=event_resolution_in_minutes)
    event_starts_after = pd.Timestamp(start_str)  # note that "" or None becomes NaT
    event_ends_before = pd.Timestamp(end_str)
    for sensor_id in sensor_ids:
        sensor = Sensor.query.get(sensor_id)
        if sensor.event_resolution == event_resolution:
            print(f"{sensor} already has the desired event resolution.")
            continue
        df_original = sensor.search_beliefs(
            most_recent_beliefs_only=False,
            event_starts_after=event_starts_after,
            event_ends_before=event_ends_before,
        ).sort_values("event_start")
        df_resampled = df_original.resample_events(event_resolution).sort_values(
            "event_start"
        )
        if not skip_integrity_check:
            message = ""
            if sensor.event_resolution < event_resolution:
                message += f"Downsampling {sensor} to {event_resolution} will result in a loss of data. "
            click.confirm(
                message
                + f"Data before:\n{df_original}\nData after:\n{df_resampled}\nMean before: {df_original['event_value'].mean()}\nMean after: {df_resampled['event_value'].mean()}\nContinue?",
                abort=True,
            )

        # Update sensor
        sensor.event_resolution = event_resolution
        db.session.add(sensor)

        # Update sensor data
        query = TimedBelief.query.filter(TimedBelief.sensor == sensor)
        if not pd.isnull(event_starts_after):
            query = query.filter(TimedBelief.event_start >= event_starts_after)
        if not pd.isnull(event_ends_before):
            query = query.filter(
                TimedBelief.event_start + sensor.event_resolution <= event_ends_before
            )
        query.delete()
        save_to_db(df_resampled, bulk_save_objects=True)
    db.session.commit()
    print("Successfully resampled sensor data.")


app.cli.add_command(fm_edit_data)


def parse_attribute_value(
    attribute_null_value: bool,
    attribute_float_value: Optional[float] = None,
    attribute_bool_value: Optional[bool] = None,
    attribute_str_value: Optional[str] = None,
    attribute_int_value: Optional[int] = None,
) -> Union[float, int, bool, str, None]:
    """Parse attribute value."""
    if not single_true(
        [attribute_null_value]
        + [
            v is not None
            for v in [
                attribute_float_value,
                attribute_bool_value,
                attribute_str_value,
                attribute_int_value,
            ]
        ]
    ):
        raise ValueError("Cannot set multiple values simultaneously.")
    if attribute_null_value:
        return None
    elif attribute_float_value is not None:
        return float(attribute_float_value)
    elif attribute_bool_value is not None:
        return bool(attribute_bool_value)
    elif attribute_int_value is not None:
        return int(attribute_int_value)
    return attribute_str_value


def single_true(iterable) -> bool:
    i = iter(iterable)
    return any(i) and not any(i)
