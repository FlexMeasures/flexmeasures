"""
CLI commands for editing data
"""

from __future__ import annotations

from datetime import timedelta

import click
import pandas as pd
from flask import current_app as app
from flask.cli import with_appcontext
import json
from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.account import AccountIdField
from sqlalchemy import delete

from flexmeasures import Sensor, Asset
from flexmeasures.data import db
from flexmeasures.data.schemas.attributes import validate_special_attributes
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db
from flexmeasures.cli.utils import MsgStyle, DeprecatedOption, DeprecatedOptionsCommand


@click.group("edit")
def fm_edit_data():
    """FlexMeasures: Edit data."""


@fm_edit_data.command("attribute", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--asset",
    "--asset-id",
    "assets",
    required=False,
    multiple=True,
    type=GenericAssetIdField(),
    cls=DeprecatedOption,
    deprecated=["--asset-id"],
    preferred="--asset",
    help="Add/edit attribute to this asset. Follow up with the asset's ID.",
)
@click.option(
    "--sensor",
    "--sensor-id",
    "sensors",
    required=False,
    multiple=True,
    type=SensorIdField(),
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
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
    "--list",
    "attribute_list_value",
    required=False,
    type=str,
    help="Set the attribute to this list value. Pass a string with a JSON-parse-able list representation, e.g. '[1,\"a\"]'.",
)
@click.option(
    "--dict",
    "attribute_dict_value",
    required=False,
    type=str,
    help="Set the attribute to this dict value. Pass a string with a JSON-parse-able dict representation, e.g. '{1:\"a\"}'.",
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
    assets: list[GenericAsset],
    sensors: list[Sensor],
    attribute_null_value: bool,
    attribute_float_value: float | None = None,
    attribute_bool_value: bool | None = None,
    attribute_str_value: str | None = None,
    attribute_int_value: int | None = None,
    attribute_list_value: str | None = None,
    attribute_dict_value: str | None = None,
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
        attribute_list_value=attribute_list_value,
        attribute_dict_value=attribute_dict_value,
        attribute_null_value=attribute_null_value,
    )

    # Some attributes with special in meaning in FlexMeasures must pass validation
    validate_special_attributes(attribute_key, attribute_value)

    # Set attribute
    for asset in assets:
        AssetAuditLog.add_record_for_attribute_update(
            attribute_key, attribute_value, "asset", asset
        )
        asset.attributes[attribute_key] = attribute_value
        db.session.add(asset)
    for sensor in sensors:
        AssetAuditLog.add_record_for_attribute_update(
            attribute_key, attribute_value, "sensor", sensor
        )
        sensor.attributes[attribute_key] = attribute_value
        db.session.add(sensor)
    db.session.commit()
    click.secho("Successfully edited/added attribute.", **MsgStyle.SUCCESS)


@fm_edit_data.command("resample-data", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_ids",
    multiple=True,
    required=True,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
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
    sensor_ids: list[int],
    event_resolution_in_minutes: int,
    start_str: str | None = None,
    end_str: str | None = None,
    skip_integrity_check: bool = False,
):
    """Assign a new event resolution to an existing sensor and resample its data accordingly."""
    event_resolution = timedelta(minutes=event_resolution_in_minutes)
    event_starts_after = pd.Timestamp(start_str)  # note that "" or None becomes NaT
    event_ends_before = pd.Timestamp(end_str)
    for sensor_id in sensor_ids:
        sensor = db.session.get(Sensor, sensor_id)
        if sensor.event_resolution == event_resolution:
            click.echo(f"{sensor} already has the desired event resolution.")
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

        AssetAuditLog.add_record(
            sensor.generic_asset,
            f"Resampled sensor data for sensor '{sensor.name}': {sensor.id} to {event_resolution} from {sensor.event_resolution}",
        )

        # Update sensor
        sensor.event_resolution = event_resolution
        db.session.add(sensor)

        # Update sensor data
        query = delete(TimedBelief).filter_by(sensor=sensor)
        if not pd.isnull(event_starts_after):
            query = query.filter(TimedBelief.event_start >= event_starts_after)
        if not pd.isnull(event_ends_before):
            query = query.filter(
                TimedBelief.event_start + sensor.event_resolution <= event_ends_before
            )
        db.session.execute(query)
        save_to_db(df_resampled, bulk_save_objects=True)
    db.session.commit()
    click.secho("Successfully resampled sensor data.", **MsgStyle.SUCCESS)


@fm_edit_data.command("transfer-ownership")
@with_appcontext
@click.option(
    "--asset",
    "asset",
    type=GenericAssetIdField(),
    required=True,
    help="Change the ownership of this asset and its children. Follow up with the asset's ID.",
)
@click.option(
    "--new-owner",
    "new_owner",
    type=AccountIdField(),
    required=True,
    help="New owner of the asset and its children.",
)
def transfer_ownership(asset: Asset, new_owner: Account):
    """
    Transfer the ownership of and asset and its children to an account.
    """

    def transfer_ownership_recursive(asset: Asset, account: Account):
        AssetAuditLog.add_record(
            asset,
            (
                f"Transferred ownership for asset '{asset.name}': {asset.id} from '{asset.owner.name}': {asset.owner.id} to '{account.name}': {account.id}"
                if asset.owner is not None
                else f"Assign ownership to public asset '{asset.name}': {asset.id} to '{account.name}': {account.id}"
            ),
        )

        asset.owner = account
        for child in asset.child_assets:
            transfer_ownership_recursive(child, account)

    transfer_ownership_recursive(asset, new_owner)
    click.secho(
        f"Success! Asset `{asset}` ownership was transferred to account `{new_owner}`.",
        **MsgStyle.SUCCESS,
    )

    db.session.commit()


app.cli.add_command(fm_edit_data)


def parse_attribute_value(  # noqa: C901
    attribute_null_value: bool,
    attribute_float_value: float | None = None,
    attribute_bool_value: bool | None = None,
    attribute_str_value: str | None = None,
    attribute_int_value: int | None = None,
    attribute_list_value: str | None = None,
    attribute_dict_value: str | None = None,
) -> float | int | bool | str | list | dict | None:
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
                attribute_list_value,
                attribute_dict_value,
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
    elif attribute_list_value is not None:
        try:
            val = json.loads(attribute_list_value)
        except json.decoder.JSONDecodeError as jde:
            raise ValueError(f"Error parsing list value: {jde}")
        if not isinstance(val, list):
            raise ValueError(f"{val} is not a list.")
        return val
    elif attribute_dict_value is not None:
        try:
            val = json.loads(attribute_dict_value)
        except json.decoder.JSONDecodeError as jde:
            raise ValueError(f"Error parsing dict value: {jde}")
        if not isinstance(val, dict):
            raise ValueError(f"{val} is not a dict.")
        return val
    return attribute_str_value


def single_true(iterable) -> bool:
    i = iter(iterable)
    return any(i) and not any(i)
