"""CLI commands for editing data."""

from __future__ import annotations

from datetime import datetime, timedelta

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
from flexmeasures.data.schemas import AssetIdField
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.audit_log import AssetAuditLog, AuditLog
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.utils import save_to_db
from flexmeasures.cli.utils import (
    MsgStyle,
    DeprecatedOption,
    DeprecatedOptionsCommand,
    abort,
)
from flexmeasures.utils.flexmeasures_inflection import pluralize
from flexmeasures.utils.secrets_utils import store_account_secret, store_asset_secret


def _resolve_secret_path(
    secret: str | None, secret_path_parts: tuple[str, ...]
) -> str | tuple[str, ...]:
    """Normalize CLI secret path arguments to a utility-friendly path."""
    if secret is not None and secret_path_parts:
        raise ValueError("Pass either --secret or --secret-path, not both.")
    if secret is None and not secret_path_parts:
        raise ValueError("Pass either --secret or --secret-path.")
    if len(secret_path_parts) > 2:
        raise ValueError("Pass --secret-path at most twice.")
    if secret_path_parts:
        return secret_path_parts
    assert secret is not None
    return secret


@click.group("edit")
def fm_edit_data():
    """FlexMeasures: Edit data."""


@fm_edit_data.command("attribute")
@with_appcontext
@click.option(
    "--account",
    "accounts",
    required=False,
    multiple=True,
    type=AccountIdField(),
    help="Add/edit attribute to this account. Follow up with the account's ID.",
)
@click.option(
    "--asset",
    "--asset-id",
    "assets",
    required=False,
    multiple=True,
    type=AssetIdField(),
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
    accounts: list[Account],
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

    if not accounts and not assets and not sensors:
        raise ValueError(
            "Missing flag: pass at least one --account, --asset or --sensor."
        )

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
    for account in accounts:
        AuditLog.add_record_for_attribute_update(
            attribute_key, attribute_value, account
        )
        account.attributes[attribute_key] = attribute_value
        db.session.add(account)
    for asset in assets:
        AssetAuditLog.add_record_for_attribute_update(
            attribute_key, attribute_value, asset
        )
        asset.attributes[attribute_key] = attribute_value
        db.session.add(asset)
    for sensor in sensors:
        AssetAuditLog.add_record_for_attribute_update(
            attribute_key, attribute_value, sensor
        )
        sensor.attributes[attribute_key] = attribute_value
        db.session.add(sensor)
    db.session.commit()
    click.secho("Successfully edited/added attribute.", **MsgStyle.SUCCESS)


@fm_edit_data.command("secret")
@with_appcontext
@click.option(
    "--account",
    "account",
    required=False,
    type=AccountIdField(),
    help="Add/edit secret on this account. Follow up with the account's ID.",
)
@click.option(
    "--asset",
    "asset",
    required=False,
    type=AssetIdField(),
    help="Add/edit secret on this asset. Follow up with the asset's ID.",
)
@click.option(
    "--secret",
    "secret",
    required=False,
    help="Add/edit this secret. Follow up with a secret name. Can also be a dot-separated path (maximally one dot), so the secret can be stored under a platform name (part before the dot).",
)
@click.option(
    "--secret-path",
    "secret_path_parts",
    required=False,
    multiple=True,
    help="Add/edit secret with this path part. Pass once or twice. Use this instead of --secret if your secret name contains a dot.",
)
@click.option(
    "--value",
    "secret_value",
    required=False,
    type=str,
    help="Set the secret to this string value.",
)
@click.option(
    "--prompt",
    "prompt_for_secret",
    required=False,
    is_flag=True,
    default=False,
    help="Prompt for the secret value without echoing it.",
)
@click.option(
    "--metadata",
    "metadata_json",
    required=False,
    type=str,
    help="Non-secret metadata to store with the encrypted value, as a JSON object.",
)
def edit_secret(
    account: Account | None,
    asset: GenericAsset | None,
    secret: str | None,
    secret_path_parts: tuple[str, ...],
    prompt_for_secret: bool,
    secret_value: str | None = None,
    metadata_json: str | None = None,
):
    """Edit (or add) an encrypted account or asset secret.

    The command accepts exactly one account or asset. Prefer ``--prompt`` over
    ``--value`` to avoid putting sensitive values in shell history.

    \b
    Examples:
      flexmeasures edit secret --account 1 --secret platform.refresh_token --prompt
      flexmeasures edit secret --asset 2 --secret-path platform --secret-path token.v2 --prompt
      flexmeasures edit secret --asset 2 --secret platform.password --value secret --metadata '{"expires_at": "2026-06-24T02:00:00"}'
    """
    if (account is None) == (asset is None):
        raise ValueError("Pass exactly one of --account or --asset.")
    if (secret_value is None) == (not prompt_for_secret):
        raise ValueError("Pass exactly one of --value or --prompt.")
    resolved_secret_path = _resolve_secret_path(secret, secret_path_parts)
    if prompt_for_secret:
        secret_value = click.prompt("Secret value", hide_input=True)
    assert secret_value is not None

    metadata = parse_secret_metadata(metadata_json)

    if account is not None:
        store_account_secret(
            account, resolved_secret_path, secret_value, metadata=metadata
        )
        db.session.add(account)
    if asset is not None:
        store_asset_secret(asset, resolved_secret_path, secret_value, metadata=metadata)
        db.session.add(asset)
    db.session.commit()
    click.secho("Successfully edited/added secret.", **MsgStyle.SUCCESS)


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
    type=AssetIdField(),
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
    Transfer the ownership of an asset and its children to an account.
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


@fm_edit_data.command("transfer-parenthood")
@with_appcontext
@click.option(
    "--asset",
    "asset",
    type=AssetIdField(),
    required=False,
    help="Change/set the parent of this asset. Follow up with the asset's ID.",
)
@click.option(
    "--new-parent",
    "new_parent",
    type=AssetIdField(),
    required=False,
    help="New parent of the asset. Follow up with the new parent's ID, or omit to orphan the asset.",
)
@click.option(
    "--old-parent",
    "old_parent",
    type=AssetIdField(),
    required=False,
    help="Change the parent of all of this asset's children. Follow up with the old parent's ID.",
)
def transfer_parenthood(
    new_parent: Asset, asset: Asset | None = None, old_parent: Asset | None = None
):
    """Transfer the parenthood of an asset, or of all children of a parent asset, to another asset.

    Either `--asset` or `--old-parent` must be specified (but not both).

    Examples:

    - Move a top-level asset 1 under asset 2:

          flexmeasures edit transfer-parenthood --asset 1 --new-parent 2

    - Reassign asset 1 to asset 3:

          flexmeasures edit transfer-parenthood --asset 1 --new-parent 3

    - Reassign all children of asset 3 to asset 4:

          flexmeasures edit transfer-parenthood --old-parent 3 --new-parent 4
    """
    validate_options_for_editing_parenthood(asset=asset, old_parent=old_parent)
    if new_parent is None:
        click.confirm(
            "No new parent specified. This will orphan the asset(s). Continue?",
            abort=True,
        )
    else:
        confirm_ownership_change(
            old_owner=(asset or old_parent).owner, new_owner=new_parent.owner
        )

    if old_parent is not None:
        assets = old_parent.child_assets
        if new_parent is None:
            message = f"Orphan {len(assets)} children from asset {old_parent.id}?"
        else:
            message = f"Reassign {len(assets)} children from asset {old_parent.id} to asset {new_parent.id}?"
        click.confirm(message, abort=True)
    else:
        assets = [asset]

    changed = 0
    for asset in assets:
        if new_parent is not None and asset.parent_asset_id == new_parent.id:
            click.secho(
                f"Asset {asset.id} already has asset {new_parent.id} as its parent. Skipping.",
                **MsgStyle.WARN,
            )
            continue
        old_parent_name = (
            asset.parent_asset.name if asset.parent_asset_id is not None else None
        )
        if new_parent is None:
            audit_log_message = f"Orphaned asset '{asset.name}' (ID: {asset.id}): from '{old_parent_name}' (ID: {asset.parent_asset_id}) to no parent"
            success_message = (
                f"Success! Asset '{asset.name}' (ID: {asset.id}) is now orphaned."
            )
        else:
            audit_log_message = f"Parent changed for asset '{asset.name}' (ID: {asset.id}): from '{old_parent_name}' (ID: {asset.parent_asset_id}) to '{new_parent.name}' (ID: {new_parent.id})"
            success_message = f"Success! Asset '{asset.name}' (ID: {asset.id}) is now a child of '{new_parent.name}' (ID: {new_parent.id})."
        if new_parent is None:
            asset.parent_asset_id = None
        else:
            asset.parent_asset_id = new_parent.id
        AssetAuditLog.add_record(asset, audit_log_message)
        click.secho(success_message, **MsgStyle.SUCCESS)
        changed += 1
    if changed == 0:
        click.secho("No assets were updated.", **MsgStyle.WARN)
    elif new_parent is None:
        click.secho(
            f"Successfully orphaned {pluralize('asset', changed, include_count=True)}.",
            **MsgStyle.SUCCESS,
        )
    else:
        click.secho(
            f"Successfully transferred {pluralize('asset', changed, include_count=True)} to new parent '{new_parent.name}' (ID: {new_parent.id}).",
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


def parse_secret_metadata(metadata_json: str | None = None) -> dict | None:
    """Parse secret metadata from a JSON object."""
    if metadata_json is None:
        return None
    try:
        metadata = json.loads(metadata_json)
    except json.decoder.JSONDecodeError as jde:
        raise ValueError(f"Error parsing secret metadata: {jde}")
    if not isinstance(metadata, dict):
        raise ValueError("Secret metadata must be a JSON object.")
    expires_at = metadata.get("expires_at")
    if expires_at is not None:
        if not isinstance(expires_at, str):
            raise ValueError("Secret metadata field 'expires_at' must be a string.")
        try:
            datetime.fromisoformat(
                f"{expires_at[:-1]}+00:00" if expires_at.endswith("Z") else expires_at
            )
        except ValueError as exc:
            raise ValueError(
                "Secret metadata field 'expires_at' must be a valid ISO datetime."
            ) from exc
    return metadata


def single_true(iterable) -> bool:
    i = iter(iterable)
    return any(i) and not any(i)


def validate_options_for_editing_parenthood(
    asset: Asset | None, old_parent: Asset | None
) -> None:
    if asset is None and old_parent is None:
        abort("Use either the `--asset` or `--old-parent` option.")
    if asset is not None and old_parent is not None:
        abort("Use either the `--asset` or `--old-parent` option.")
    if old_parent is not None:
        assets = old_parent.child_assets
        if not assets:
            abort(f"Asset {old_parent.id} has no child assets.")


def confirm_ownership_change(
    old_owner: Account | None, new_owner: Account | None
) -> None:
    if old_owner is None and new_owner is not None:
        # public → owned
        click.confirm(
            f"You are moving public asset(s) under an account-owned parent: "
            f"{new_owner.name} (ID: {new_owner.id}). Continue?",
            abort=True,
        )
    elif old_owner is not None and new_owner is None:
        # owned → public
        click.confirm(
            f"You are moving asset(s) from account {old_owner.name} (ID: {old_owner.id}) "
            "under a public parent (no owner). Continue?",
            abort=True,
        )
    elif old_owner != new_owner:
        # cross-account move
        click.confirm(
            f"You are moving asset(s) from account {old_owner.name} (ID: {old_owner.id}) "
            f"under a parent in a different account: {new_owner.name} (ID: {new_owner.id}). Continue?",
            abort=True,
        )
