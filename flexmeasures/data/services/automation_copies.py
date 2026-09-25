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
    WINDOW_FIELDS,
    get_forecast_output_sensor,
    validate_automation_output_scope,
)
from flexmeasures.data.services.data_sources import get_or_create_source

# The automation types whose output sensors have to sit in the automation's own asset subtree, as `create_automation` requires.
OUTPUT_SCOPED_AUTOMATION_TYPES = frozenset({"forecasting", "reporting"})

# The automation types a copy can point at the copied sensors.
# A schedule automation's parameters are a trigger message,
# whose flex config holds sensor references in fields that no schema walks (the trigger's 'flex-context' is a raw field),
# so copying one would quietly keep computing with the original's sensors.
COPYABLE_AUTOMATION_TYPES = frozenset({"forecasting", "reporting"})

# The parameters an automation leaves to each run, which its stored parameters therefore do not hold.
# A data generator's schema requires or refuses these, so they are set aside while the stored parameters are checked.
# The window fields describe when a run computes (see `resolve_automation_window`), and 'start' and 'end' are what a report resolves them into.
RUN_TIME_RESOLVED_PARAMETERS = tuple(WINDOW_FIELDS) + ("start", "end")

# Any window will do: it stands in for the one each run resolves, only while the other parameters are checked.
PLACEHOLDER_WINDOW = {
    "start": "2020-01-01T00:00:00+00:00",
    "end": "2020-01-02T00:00:00+00:00",
}


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
        except Exception as e:
            # Whatever an automation's stored data generator does on the way in, it does not take the asset copy with it.
            # Its class may be gone, its configuration may no longer load, or its constructor may refuse what was stored.
            current_app.logger.warning(
                "Skipped copying automation %s ('%s') from asset %s: %s",
                automation.id,
                automation.name,
                automation.asset_id,
                e,
                exc_info=True,
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
    if automation.type not in COPYABLE_AUTOMATION_TYPES:
        raise AutomationNotCopyable(
            f"An automation of type '{automation.type}' cannot be copied yet:"
            " its parameters hold sensor references that a copy cannot point at the copied sensors."
        )
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
    if automation.type in OUTPUT_SCOPED_AUTOMATION_TYPES:
        # Reject a copy whose results would land outside its own asset, rather than let it fail on every run.
        try:
            for output_sensor in _output_sensors(automation.type, parameters):
                validate_automation_output_scope(
                    copied_asset_id, output_sensor, automation.type
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
    except ValidationError as e:
        raise AutomationNotCopyable(
            f"Its stored data generator configuration no longer validates: {e.messages}"
        ) from e
    except Exception as e:
        # A data generator's own constructor decides what it accepts, and a stored configuration can outlive that.
        raise AutomationNotCopyable(
            f"Its data generator could not be set up: {e.__class__.__name__}: {e}"
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
    A configuration that does need remapping goes onto its own data source,
    so that editing or deleting the copy cannot change the original automation's generator.

    :raises AutomationNotCopyable: if the remapped configuration does not validate.
    """
    if not _account_can_read(generator.account_id, destination_account_id):
        raise AutomationNotCopyable(
            f"Its data generator is data source {generator.id}, which the destination organisation cannot read."
        )

    config = _stored_generator_config(generator)
    config_schema = data_generator._config_schema
    if config_schema is None:
        raise AutomationNotCopyable(
            "Its data generator does not describe the configuration it takes,"
            " so a copy could not point its sensor references at the copied sensors."
        )
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
    # The copy records under a data source of the organisation it lands in, rather than of the one it came from,
    # so that what the copy computes is that organisation's own data, and its source filters find it.
    destination_account = (
        db.session.get(Account, destination_account_id)
        if destination_account_id is not None
        else None
    )
    return get_or_create_source(
        source=generator.name,
        source_type=generator.type,
        model=generator.model,
        version=generator.version,
        attributes=attributes,
        account=destination_account,
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
        # A schedule automation's parameters are a trigger message, which its scheduler does not describe.
        # Its flex config holds sensor references in fields that no schema walks (the trigger's 'flex-context' is a raw field),
        # so a copy could not point them at the copied sensors, and would quietly keep computing with the original's.
        raise AutomationNotCopyable(
            f"An automation of type '{automation.type}' cannot be copied yet:"
            " its parameters describe no sensor references that a copy could point at the copied sensors."
        )
    parameters = deepcopy(dict(automation.parameters or {}))
    remapped_parameters = remapper.remap(parameters, parameters_schema)
    # An automation stores what stays the same between its runs, so the schema sees it without what each run resolves.
    # Checking those fields here would refuse an automation for timing it the way automations are timed.
    to_check = {
        field: value
        for field, value in remapped_parameters.items()
        if field not in RUN_TIME_RESOLVED_PARAMETERS
    }
    # A schema which requires a window, as a reporter's does, is given one,
    # so that the rest of the parameters is checked the way the run will present them,
    # rather than refused for a window the run has yet to resolve.
    for field, stand_in in PLACEHOLDER_WINDOW.items():
        if field in parameters_schema.fields and field not in to_check:
            to_check[field] = stand_in
    # Validate the fields rather than load them:
    # loading would also run what the schema derives from a whole run's parameters,
    # such as a forecast's prediction window, which the fields set aside above are part of.
    errors = parameters_schema.validate(to_check, partial=RUN_TIME_RESOLVED_PARAMETERS)
    if errors:
        raise AutomationNotCopyable(
            f"Its parameters do not hold up after remapping: {errors}"
        )
    return remapped_parameters


def _user_can_read(sensor_or_asset) -> bool:
    """Whether the user doing the copying may read this themselves, where there is one.

    The organisation a copy lands in may read a client's data through a consultancy relation,
    but only its users with the consultant role do (see `GenericAsset.__acl__`).
    A copy is made on someone's behalf, so what it keeps a reference to is held to what that someone may read,
    the way `create_automation` holds a new automation to its creator (see `check_sensor_access`).
    """
    from flask_security import current_user
    from flexmeasures.auth.policy import check_access
    from werkzeug.exceptions import Forbidden

    if not current_user or not getattr(current_user, "is_authenticated", False):
        # Copying outside a request, as a script does, is held to the organisation check alone.
        return True
    try:
        check_access(sensor_or_asset, "read")
    except Forbidden:
        return False
    return True


def _account_can_read(
    owner_account_id: int | None, destination_account_id: int | None
) -> bool:
    """Whether the organisation a copy lands in may read data owned by another organisation.

    Anything public is readable,
    and so is anything owned by the destination organisation itself or by an organisation it consults for.
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


def _output_sensors(automation_type: str, parameters: dict) -> list[Sensor]:
    """The sensors a copied forecast or report automation records on, read from its remapped parameters.

    :raises ValueError: if one of them does not exist.
    """
    if automation_type == "forecasting":
        return [get_forecast_output_sensor(parameters)]
    sensors = []
    for output in parameters.get("output", []) or []:
        if not isinstance(output, dict) or output.get("sensor") is None:
            continue
        sensor = db.session.get(Sensor, int(output["sensor"]))
        if sensor is None:
            raise ValueError(f"Report output sensor {output['sensor']} does not exist.")
        sensors.append(sensor)
    return sensors


def _field_name(field: fields.Field) -> str:
    """Name a schema field the way it is spelled in the stored data."""
    return field.data_key or field.name or "value"


def _require_stored_type(
    value, expected: type, described_as: str, field: fields.Field
) -> None:
    """Require a stored value to have the shape its schema field describes.

    :raises AutomationNotCopyable: if it does not, as its references then cannot be checked.
    """
    if not isinstance(value, expected):
        raise AutomationNotCopyable(
            f"Its stored {_field_name(field)} is {type(value).__name__} rather than {described_as}, so its references cannot be checked."
        )


def _reference_id(value, kind: str) -> int:
    """Read one stored reference as an ID.

    Configuration and parameters are stored as JSON that a schema wrote but that nothing re-checks on the way out,
    so a value that is not an ID means this one automation cannot be checked,
    not that the whole asset copy should fail.

    :raises AutomationNotCopyable: if the value cannot be read as an ID.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str, float)):
        raise AutomationNotCopyable(
            f"It holds {value!r} where a {kind} ID belongs, so its references cannot be checked."
        )
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise AutomationNotCopyable(
            f"It holds {value!r} where a {kind} ID belongs, so its references cannot be checked."
        ) from e


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

    # NB a field which describes no fields of its own, such as a mapping of settings, is kept as it is.
    # No schema in FlexMeasures holds a sensor, asset, data source or organisation reference in such a field,
    # and one that did would have its references kept rather than pointed at the copies,
    # so a data generator which takes references that way cannot be copied correctly.

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
            _require_stored_type(value, list, "a list", field)
            return [self._remap_value(item, field.inner) for item in value]
        if isinstance(field, fields.Nested):
            _require_stored_type(value, dict, "an object", field)
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
        sensor_id = _reference_id(value, "sensor")
        if sensor_id in self.sensor_id_map:
            return self.sensor_id_map[sensor_id]
        sensor = db.session.get(Sensor, sensor_id)
        if sensor is None:
            raise AutomationNotCopyable(
                f"It references sensor {sensor_id}, which no longer exists."
            )
        asset = db.session.get(GenericAsset, sensor.generic_asset_id)
        owner_account_id = asset.account_id if asset is not None else None
        if (
            asset is None
            or not _account_can_read(owner_account_id, self.destination_account_id)
            or not _user_can_read(sensor)
        ):
            raise AutomationNotCopyable(
                f"It references sensor {sensor_id}, which lies outside the copied assets and which the destination organisation cannot read."
            )
        return sensor_id

    def _remap_asset_id(self, value) -> int:
        """Point an asset reference at the copied asset, or keep it if the destination may read it."""
        asset_id = _reference_id(value, "asset")
        if asset_id in self.asset_id_map:
            return self.asset_id_map[asset_id]
        asset = db.session.get(GenericAsset, asset_id)
        if asset is None:
            raise AutomationNotCopyable(
                f"It references asset {asset_id}, which no longer exists."
            )
        if not _account_can_read(
            asset.account_id, self.destination_account_id
        ) or not _user_can_read(asset):
            raise AutomationNotCopyable(
                f"It references asset {asset_id}, which lies outside the copied assets and which the destination organisation cannot read."
            )
        return asset_id

    def _check_data_source_id(self, value) -> None:
        """Refuse a data source reference the destination organisation cannot read."""
        source_id = _reference_id(value, "data source")
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
        account_id = _reference_id(value, "organisation")
        if not _account_can_read(account_id, self.destination_account_id):
            raise AutomationNotCopyable(
                f"It references organisation {account_id}, whose data the destination organisation cannot read."
            )
