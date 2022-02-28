from datetime import timedelta
from typing import Union, List, Optional

import click
import pandas as pd
from flask import current_app as app
from flask.cli import with_appcontext

from flexmeasures import Sensor
from flexmeasures.data import db
from flexmeasures.data.schemas.generic_assets import GenericAssetField
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db


@click.group("edit")
def fm_edit_data():
    """FlexMeasures: Edit data."""


@fm_edit_data.command("asset-attribute")
@with_appcontext
@click.option(
    "--asset-id",
    "asset",
    required=True,
    type=GenericAssetField(),
    help="Add/edit attribute to this asset. Follow up with the asset's ID.",
)
@click.option(
    "--attribute",
    "attribute_key",
    required=True,
    help="Add/edit this attribute. Follow up with the name of the asset attribute.",
)
@click.option(
    "--value",
    "attribute_value",
    required=True,
    help="Set the asset attribute to this float value. Use --type to set a type other than a float. Use 'None' to set a null value.",
)
@click.option(
    "--type",
    "attribute_value_type",
    required=False,
    default="float",
    type=click.Choice(["bool", "str", "int", "float"]),
    help="Parse the asset attribute value as this type.",
)
def edit_asset_attribute(
    asset: GenericAsset,
    attribute_key: str,
    attribute_value: Union[bool, str, int, float, None],
    attribute_value_type: str,
):
    """Edit (or add) an asset attribute."""

    # Parse attribute value
    attribute_value = parse_attribute_value(
        attribute_value=attribute_value,
        attribute_value_type=attribute_value_type,
    )

    # Set attribute
    asset.attributes[attribute_key] = attribute_value
    db.session.add(asset)
    db.session.commit()


@fm_edit_data.command("sensor-attribute")
@with_appcontext
@click.option(
    "--sensor-id",  # todo: use SensorField
    "sensor_id",
    required=True,
    help="Add/edit attribute to this sensor. Follow up with the sensor's ID.",
)
@click.option(
    "--attribute",
    "attribute_key",
    required=True,
    help="Add/edit this attribute. Follow up with the name of the sensor attribute.",
)
@click.option(
    "--value",
    "attribute_value",
    required=True,
    help="Set the sensor attribute to this float value. Use --type to set a type other than a float. Use 'None' to set a null value.",
)
@click.option(
    "--type",
    "attribute_value_type",
    required=False,
    default="float",
    type=click.Choice(["bool", "str", "int", "float"]),
    help="Parse the asset attribute value as this type.",
)
def edit_sensor_attribute(
    sensor_id: int,
    attribute_key: str,
    attribute_value: Union[bool, str, int, float, None],
    attribute_value_type: str,
):
    """Edit (or add) a sensor attribute."""

    # Parse attribute value
    attribute_value = parse_attribute_value(
        attribute_value=attribute_value,
        attribute_value_type=attribute_value_type,
    )

    # Set attribute
    sensor = Sensor.query.get(sensor_id)
    sensor.attributes[attribute_key] = attribute_value
    db.session.add(sensor)
    db.session.commit()


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
    attribute_value: str, attribute_value_type: str
) -> Union[float, int, bool, str, None]:
    """Parse attribute value."""
    if attribute_value == "None":
        attribute_value = None
    elif attribute_value_type == "float":
        attribute_value = float(attribute_value)
    elif attribute_value_type == "int":
        attribute_value = int(attribute_value)
    elif attribute_value_type == "bool":
        attribute_value = bool(attribute_value)
    elif attribute_value_type == "str":
        pass
    else:
        raise ValueError(f"Unrecognized --type '{attribute_value_type}'.")
    return attribute_value
