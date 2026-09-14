"""
Copying automations along with the asset subtree they belong to (see `copy_asset`).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from flask import current_app
from marshmallow import Schema, ValidationError, fields
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.automations import Automation, get_initial_cursor
from flexmeasures.data.models.data_sources import DataGenerator, DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.account import AccountIdField, AccountIdOrListField
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import SensorIdField, SensorIdOrReferenceField
from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.services.automations import (
    get_forecast_output_sensor,
    validate_forecast_output_scope,
)
from flexmeasures.data.services.data_sources import get_or_create_source


@dataclass(frozen=True)
class SkippedAutomation:
    """One automation that was left out of an asset copy, and why."""

    automation_id: int
    name: str
    asset_id: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Render for an API response."""
        return {
            "id": self.automation_id,
            "name": self.name,
            "asset": self.asset_id,
            "reason": self.reason,
        }


class AutomationNotCopyable(Exception):
    """Raised when one automation cannot be copied safely.

    The asset copy goes ahead without it, so the message is shown to whoever asked for the copy;
    phrase it as a complete sentence that says what stood in the way.
    """


def copy_automations(
    asset_id_map: dict[int, int],
    sensor_id_map: dict[int, int],
    destination_account_id: int | None,
) -> list[SkippedAutomation]:
    """Copy the automations of a freshly copied asset subtree, leaving each copy inactive.

    Every automation on a copied asset is copied onto the corresponding new asset,
    with its references to sensors inside the subtree pointed at the new sensors.
    A copy keeps its name, type, cron expression and timezone, but starts inactive and with a fresh cursor,
    so that it inherits neither the original's run history nor its queued jobs.

    An automation that cannot be copied safely is skipped rather than failing the asset copy:
    the copied asset, its sensors and the other automations are kept.
    Each skipped automation is logged and returned, so that the caller can report it.

    :param asset_id_map:            Mapping of every original asset ID in the copied subtree to its new asset ID.
    :param sensor_id_map:           Mapping of every original sensor ID in the copied subtree to its new sensor ID.
    :param destination_account_id:  The account the copy belongs to, or None if the copy is public.
    :returns:                       The automations that were skipped, in the order they were considered.
    """
    if not asset_id_map:
        return []

    # Put the copied assets and sensors on record before opening any savepoint,
    # so that rolling one back can only undo the automation it was opened for.
    db.session.flush()

    source_automations = (
        db.session.scalars(
            select(Automation)
            .filter(Automation.asset_id.in_(list(asset_id_map)))
            .order_by(Automation.id)
        )
        .unique()
        .all()
    )

    skipped: list[SkippedAutomation] = []
    for automation in source_automations:
        try:
            with db.session.begin_nested():
                _copy_automation(
                    automation=automation,
                    asset_id_map=asset_id_map,
                    sensor_id_map=sensor_id_map,
                    destination_account_id=destination_account_id,
                )
        except AutomationNotCopyable as e:
            current_app.logger.warning(
                "Skipped copying automation %s ('%s') from asset %s: %s",
                automation.id,
                automation.name,
                automation.asset_id,
                e,
            )
            skipped.append(
                SkippedAutomation(
                    automation_id=automation.id,
                    name=automation.name,
                    asset_id=automation.asset_id,
                    reason=str(e),
                )
            )
    return skipped


def _copy_automation(
    automation: Automation,
    asset_id_map: dict[int, int],
    sensor_id_map: dict[int, int],
    destination_account_id: int | None,
) -> Automation:
    """Copy one automation onto the copy of the asset it belongs to.

    :raises AutomationNotCopyable: if the copy would not be safe or would not run.
    """
    data_generator = _load_data_generator(automation)
    remapper = _ReferenceRemapper(
        sensor_id_map=sensor_id_map,
        asset_id_map=asset_id_map,
        destination_account_id=destination_account_id,
    )

    generator = _copy_generator(
        automation.generator, data_generator, remapper, destination_account_id
    )
    parameters = _copy_parameters(automation, data_generator, remapper)

    copied_asset_id = asset_id_map[automation.asset_id]
    if automation.type == "forecasts":
        # Reject a copy whose forecast would land outside its own asset, rather than let it fail on every run.
        try:
            validate_forecast_output_scope(
                copied_asset_id, get_forecast_output_sensor(parameters)
            )
        except ValueError as e:
            raise AutomationNotCopyable(str(e)) from e

    copied_automation = Automation(
        asset_id=copied_asset_id,
        type=automation.type,
        name=automation.name,
        cronstr=automation.cronstr,
        timezone=automation.timezone,
        # A copy starts inactive, so that it can be inspected and tested before it runs.
        active=False,
        generator_id=generator.id,
        parameters=parameters,
        # A fresh cursor, so that the copy does not inherit the original's run history.
        cursor=get_initial_cursor(),
    )
    db.session.add(copied_automation)
    db.session.flush()
    return copied_automation


def _load_data_generator(automation: Automation) -> DataGenerator:
    """Set up the data generator of an automation, so that its configuration can be read and remapped.

    :raises AutomationNotCopyable: if the automation has no data generator, or if its class is not available here.
    """
    if automation.generator is None:
        raise AutomationNotCopyable("It has no data generator.")
    try:
        return automation.generator.data_generator
    except NotImplementedError as e:
        raise AutomationNotCopyable(
            f"Its data generator could not be set up: {e}"
        ) from e


def _copy_generator(
    generator: DataSource,
    data_generator: DataGenerator,
    remapper: "_ReferenceRemapper",
    destination_account_id: int | None,
) -> DataSource:
    """Return the data source that should store the copied automation's generator configuration.

    The original data source is reused as long as its configuration needs no remapping,
    which is how data sources are shared between automations that are configured alike.
    A configuration that does need remapping goes onto its own data source, so that editing or deleting the copy
    cannot change the original automation's generator.

    :raises AutomationNotCopyable: if the remapped configuration does not validate.
    """
    if not _account_can_read(generator.account_id, destination_account_id):
        raise AutomationNotCopyable(
            f"Its data generator is data source {generator.id}, which the destination organisation cannot read."
        )

    config = _stored_generator_config(generator)
    config_schema = data_generator._config_schema
    remapped_config = remapper.remap(config, config_schema)
    if remapped_config == config:
        return generator

    try:
        config_schema.load(remapped_config)
    except ValidationError as e:
        raise AutomationNotCopyable(
            f"Its data generator configuration does not hold up after remapping: {e.messages}"
        ) from e

    attributes = deepcopy(dict(generator.attributes or {}))
    attributes.setdefault("data_generator", {})["config"] = remapped_config
    return get_or_create_source(
        source=generator.name,
        source_type=generator.type,
        model=generator.model,
        version=generator.version,
        attributes=attributes,
        account=generator.account,
    )


def _stored_generator_config(generator: DataSource) -> dict:
    """Read the generator configuration as it is stored on a data source."""
    return deepcopy(
        (generator.attributes or {}).get("data_generator", {}).get("config", {})
    )


def _copy_parameters(
    automation: Automation,
    data_generator: DataGenerator,
    remapper: "_ReferenceRemapper",
) -> dict:
    """Remap the parameters an automation calls its data generator with.

    :raises AutomationNotCopyable: if the remapped parameters do not validate.
    """
    parameters_schema = data_generator._parameters_schema
    if parameters_schema is None:
        raise AutomationNotCopyable(
            "Its data generator does not describe the parameters it takes, so its sensor references cannot be remapped."
        )
    parameters = deepcopy(dict(automation.parameters or {}))
    remapped_parameters = remapper.remap(parameters, parameters_schema)
    try:
        parameters_schema.load(remapped_parameters)
    except ValidationError as e:
        raise AutomationNotCopyable(
            f"Its parameters do not hold up after remapping: {e.messages}"
        ) from e
    return remapped_parameters


def _account_can_read(
    owner_account_id: int | None, destination_account_id: int | None
) -> bool:
    """Whether the organisation a copy lands in may read data owned by another organisation.

    Anything public is readable, and so is anything owned by the destination organisation itself
    or by an organisation it consults for.
    A public copy may only rely on public data, as it is readable by every organisation.
    """
    if owner_account_id is None:
        return True
    if destination_account_id is None:
        return False
    if owner_account_id == destination_account_id:
        return True
    owner = db.session.get(Account, owner_account_id)
    return owner is not None and owner.consultancy_account_id == destination_account_id


class _ReferenceRemapper:
    """Points the references in a serialized configuration or parameter set at a copied subtree.

    A reference to something inside the copied subtree becomes a reference to its copy.
    A reference to something outside it is kept only if the destination organisation may read it;
    otherwise the automation holding the reference cannot be copied safely.

    The traversal is driven by the marshmallow schema that describes the data,
    so it follows whichever fields a data generator declares as sensor, asset, account or data source references.
    That keeps it working for automation types other than forecasts, and for generators that plugins add.
    """

    def __init__(
        self,
        sensor_id_map: dict[int, int],
        asset_id_map: dict[int, int],
        destination_account_id: int | None,
    ):
        self.sensor_id_map = sensor_id_map
        self.asset_id_map = asset_id_map
        self.destination_account_id = destination_account_id

    def remap(self, data: dict, schema: Schema) -> dict:
        """Return a copy of serialized `data` with its references remapped.

        :raises AutomationNotCopyable: if a reference can be neither remapped nor safely kept.
        """
        remapped = deepcopy(data)
        for field_name, field in schema.fields.items():
            key = field.data_key or field_name
            if key not in remapped:
                continue
            remapped[key] = self._remap_value(remapped[key], field)
        return remapped

    def _remap_value(self, value, field: fields.Field):
        """Remap one value, as far as the field describing it calls for."""
        if value is None:
            return None
        if isinstance(field, fields.List):
            return [self._remap_value(item, field.inner) for item in value]
        if isinstance(field, fields.Nested):
            return self.remap(value, field.schema)
        if isinstance(field, SensorIdOrReferenceField):
            if isinstance(value, dict):
                return self.remap(value, field.sensor_reference_schema)
            return self._remap_sensor_id(value)
        if isinstance(field, SensorIdField):
            return self._remap_sensor_id(value)
        if isinstance(field, GenericAssetIdField):
            return self._remap_asset_id(value)
        if isinstance(field, DataSourceIdField):
            self._check_data_source_id(value)
            return value
        if isinstance(field, AccountIdField):
            self._check_account_id(value)
            return value
        if isinstance(field, AccountIdOrListField):
            for account_id in value if isinstance(value, list) else [value]:
                self._check_account_id(account_id)
            return value
        return value

    def _remap_sensor_id(self, value) -> int:
        """Point a sensor reference at the copied sensor, or keep it if the destination may read it."""
        sensor_id = int(value)
        if sensor_id in self.sensor_id_map:
            return self.sensor_id_map[sensor_id]
        sensor = db.session.get(Sensor, sensor_id)
        if sensor is None:
            raise AutomationNotCopyable(
                f"It references sensor {sensor_id}, which no longer exists."
            )
        asset = db.session.get(GenericAsset, sensor.generic_asset_id)
        owner_account_id = asset.account_id if asset is not None else None
        if asset is None or not _account_can_read(
            owner_account_id, self.destination_account_id
        ):
            raise AutomationNotCopyable(
                f"It references sensor {sensor_id}, which lies outside the copied assets and which the destination organisation cannot read."
            )
        return sensor_id

    def _remap_asset_id(self, value) -> int:
        """Point an asset reference at the copied asset, or keep it if the destination may read it."""
        asset_id = int(value)
        if asset_id in self.asset_id_map:
            return self.asset_id_map[asset_id]
        asset = db.session.get(GenericAsset, asset_id)
        if asset is None:
            raise AutomationNotCopyable(
                f"It references asset {asset_id}, which no longer exists."
            )
        if not _account_can_read(asset.account_id, self.destination_account_id):
            raise AutomationNotCopyable(
                f"It references asset {asset_id}, which lies outside the copied assets and which the destination organisation cannot read."
            )
        return asset_id

    def _check_data_source_id(self, value) -> None:
        """Refuse a data source reference the destination organisation cannot read."""
        source_id = int(value)
        source = db.session.get(DataSource, source_id)
        if source is None:
            raise AutomationNotCopyable(
                f"It references data source {source_id}, which no longer exists."
            )
        if not _account_can_read(source.account_id, self.destination_account_id):
            raise AutomationNotCopyable(
                f"It references data source {source_id}, which the destination organisation cannot read."
            )

    def _check_account_id(self, value) -> None:
        """Refuse an organisation reference the destination organisation cannot read."""
        account_id = int(value)
        if not _account_can_read(account_id, self.destination_account_id):
            raise AutomationNotCopyable(
                f"It references organisation {account_id}, whose data the destination organisation cannot read."
            )
