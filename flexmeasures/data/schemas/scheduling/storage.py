from __future__ import annotations

from typing import TypedDict, cast, Callable
from datetime import datetime, timedelta

from flask import current_app
from marshmallow import (
    Schema,
    post_load,
    validate,
    validates_schema,
    fields,
    validates,
)
from marshmallow.validate import OneOf, ValidationError

from flexmeasures import Asset, Sensor
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.scheduling import metadata
from flexmeasures.data.schemas.sensors import (
    SensorIdField,
    SensorReference,
    SharedSensorReferenceSchema,
    OutputSensorReferenceSchema,
    VariableQuantityField,
)
from flexmeasures.utils.unit_utils import (
    ur,
    is_power_unit,
    is_energy_unit,
)

ALLOWED_COMMODITIES = {"electricity", "gas"}


def _validate_group_sensor_is_power_sensor(group: dict):
    """Check that the sensor referenced by the `group` field measures power."""
    sensor = group.get("sensor")
    if isinstance(sensor, (Sensor, SensorReference)) and not is_power_unit(sensor.unit):
        raise ValidationError(
            "The `group` field must reference a sensor with a power unit.",
            field_name="group",
        )


def _validate_coupling_name(coupling: str | None):
    """Reject blank/whitespace-only coupling names.

    A blank coupling name would become a coupling-group key, silently coupling
    unrelated devices under an empty group. When provided, the name must contain
    at least one non-whitespace character.
    """
    if coupling is not None and not coupling.strip():
        raise ValidationError(
            "The `coupling` field, when provided, must be a non-empty (non-whitespace) name.",
            field_name="coupling",
        )


class GroupReferenceSchema(SharedSensorReferenceSchema):
    """Reference to a group of devices whose aggregate power is constrained.

    Accepts exactly one of:
      - ``{"sensor": <id>}``: the group's aggregate power is stored on this power sensor
        (the sensor must itself carry a flex-model entry defining the group's
        constraints).
      - ``{"asset": <id>}``: the group is identified by the flex-model entry on this
        asset (typically a sub-EMS/asset in the tree). Such a group entry defines no
        power sensor of its own; instead it may define ``consumption`` and/or
        ``production`` output sensors on which the group's aggregate power gets saved,
        following the usual output-sensor conventions.

    Inherits from ``SharedSensorReferenceSchema`` (not ``SensorReferenceSchema``) so it
    accepts only ``sensor``/``asset`` -- a group is a device-group identifier, not a
    belief-query reference, so the ``source-*`` filter fields do not apply.
    """

    class Meta:
        description = (
            "Reference to a group of devices whose aggregate power is constrained."
        )

    sensor = SensorIdField(required=False)
    asset = GenericAssetIdField(required=False)

    @validates_schema
    def validate_exactly_one_reference(self, data: dict, **kwargs):
        has_sensor = "sensor" in data
        has_asset = "asset" in data
        if has_sensor == has_asset:  # both or neither
            raise ValidationError(
                "The `group` field must reference exactly one of 'sensor' or 'asset'."
            )


#  Telling type hints what to expect after schema parsing
SoCTarget = TypedDict(
    "SoCTarget",
    {
        "datetime": datetime,
        "start": datetime,
        "end": datetime,
        "duration": timedelta,
        "value": float,
    },
    total=False,  # not all are required (just value, which we can say in 3.11)
)


class EfficiencyField(QuantityField):
    """Field that deserializes to a Quantity with % units.
    Fixed values must be greater than 0% and less than or equal to 100%.

    Examples:

        >>> ef = EfficiencyField()
        >>> ef.deserialize(0.9)
        <Quantity(90.0, 'percent')>
        >>> ef.deserialize("90%")
        <Quantity(90, 'percent')>
        >>> ef.deserialize("0%")
        Traceback (most recent call last):
        ...
        marshmallow.exceptions.ValidationError: ['Must be greater than 0 % and less than or equal to 100 %.']
    """

    def __init__(self, *args, **kwargs):
        super().__init__(
            "%",
            validate=validate.Range(
                min=ur.Quantity("0%"),
                max=ur.Quantity("100%"),
                min_inclusive=False,
                max_inclusive=True,
            ),
            *args,
            **kwargs,
        )


class StorageFlexModelSchema(Schema):
    """
    This schema lists fields we require when scheduling storage assets.
    Some fields are not required, as they might live on the Sensor.attributes.
    You can use StorageScheduler.deserialize_flex_config to get that filled in.
    """

    asset = GenericAssetIdField(
        required=False,
        metadata=dict(description="ID of the asset that is requested to be scheduled."),
    )

    commodity = fields.Str(
        data_key="commodity",
        load_default="electricity",
        metadata=metadata.COMMODITY_FLEX_MODEL.to_dict(),
    )

    consumption = fields.Nested(
        OutputSensorReferenceSchema,
        metadata=metadata.CONSUMPTION.to_dict(),
    )
    production = fields.Nested(
        OutputSensorReferenceSchema,
        metadata=metadata.PRODUCTION.to_dict(),
    )

    soc_at_start = QuantityField(
        required=False,
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=False,
        data_key="soc-at-start",
        metadata=metadata.SOC_AT_START.to_dict(),
    )

    soc_min = QuantityField(
        validate=validate.Range(min=ur.Quantity("0 MWh")),
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=False,
        data_key="soc-min",
        metadata=metadata.SOC_MIN.to_dict(),
    )
    soc_max = QuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=False,
        data_key="soc-max",
        metadata=metadata.SOC_MAX.to_dict(),
    )

    power_capacity_in_mw = VariableQuantityField(
        "MW",
        required=False,
        data_key="power-capacity",
        metadata=metadata.POWER_CAPACITY.to_dict(),
    )

    consumption_capacity = VariableQuantityField(
        "MW",
        data_key="consumption-capacity",
        required=False,
        metadata=metadata.CONSUMPTION_CAPACITY.to_dict(),
    )
    production_capacity = VariableQuantityField(
        "MW",
        data_key="production-capacity",
        required=False,
        metadata=metadata.PRODUCTION_CAPACITY.to_dict(),
    )

    group = fields.Nested(
        GroupReferenceSchema,
        data_key="group",
        required=False,
        metadata=metadata.GROUP.to_dict(),
    )

    # Activation prices
    prefer_curtailing_later = fields.Bool(
        data_key="prefer-curtailing-later",
        load_default=True,
        metadata=metadata.PREFER_CURTAILING_LATER.to_dict(),
    )
    prefer_charging_sooner = fields.Bool(
        data_key="prefer-charging-sooner",
        load_default=True,
        metadata=metadata.PREFER_CHARGING_SOONER.to_dict(),
    )

    # Timezone placeholders for the soc_maxima, soc_minima and soc_targets fields are overridden in __init__
    soc_maxima = VariableQuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        timezone="placeholder",
        data_key="soc-maxima",
        metadata=metadata.SOC_MAXIMA.to_dict(),
    )

    soc_minima = VariableQuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        timezone="placeholder",
        data_key="soc-minima",
        value_validator=validate.Range(min=0),
        metadata=metadata.SOC_MINIMA.to_dict(),
    )

    soc_targets = VariableQuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        timezone="placeholder",
        data_key="soc-targets",
        metadata=metadata.SOC_TARGETS.to_dict(),
    )

    soc_unit = fields.Str(
        validate=OneOf(
            [
                "kWh",
                "MWh",
            ]
        ),
        data_key="soc-unit",
        required=False,
        metadata=metadata.SOC_UNIT.to_dict(),
    )

    state_of_charge = VariableQuantityField(
        to_unit="MWh",
        data_key="state-of-charge",
        required=False,
        additional_sensor_units=["%"],
        metadata=metadata.STATE_OF_CHARGE.to_dict(),
    )

    charging_efficiency = VariableQuantityField(
        "%",
        data_key="charging-efficiency",
        required=False,
        metadata=metadata.CHARGING_EFFICIENCY.to_dict(),
    )
    discharging_efficiency = VariableQuantityField(
        "%",
        data_key="discharging-efficiency",
        required=False,
        metadata=metadata.DISCHARGING_EFFICIENCY.to_dict(),
    )

    roundtrip_efficiency = EfficiencyField(
        data_key="roundtrip-efficiency",
        required=False,
        metadata=metadata.ROUNDTRIP_EFFICIENCY.to_dict(),
    )

    storage_efficiency = VariableQuantityField(
        "%",
        data_key="storage-efficiency",
        metadata=metadata.STORAGE_EFFICIENCY.to_dict(),
    )

    soc_gain = fields.List(
        VariableQuantityField("MW"),
        data_key="soc-gain",
        required=False,
        validate=validate.Length(min=1),
        metadata=metadata.SOC_GAIN.to_dict(),
    )
    soc_usage = fields.List(
        VariableQuantityField("MW"),
        data_key="soc-usage",
        required=False,
        validate=validate.Length(min=1),
        metadata=metadata.SOC_USAGE.to_dict(),
    )
    coupling = fields.Str(
        data_key="coupling",
        required=False,
        load_default=None,
        metadata=metadata.COUPLING.to_dict(),
    )
    coupling_coefficient = fields.Float(
        data_key="coupling-coefficient",
        required=False,
        load_default=1.0,
        validate=validate.Range(min=0, min_inclusive=False),
        metadata=metadata.COUPLING_COEFFICIENT.to_dict(),
    )
    coupling_base = QuantityField(
        "MW",
        data_key="coupling-base",
        required=False,
        validate=validate.Range(min=ur.Quantity("0 MW")),
        metadata=metadata.COUPLING_BASE.to_dict(),
    )
    coupling_min = QuantityField(
        "MW",
        data_key="coupling-min",
        required=False,
        validate=validate.Range(min=ur.Quantity("0 MW")),
        metadata=metadata.COUPLING_MIN.to_dict(),
    )

    def __init__(
        self,
        start: datetime,
        sensor: Sensor | None,
        *args,
        default_soc_unit: str | None = None,
        **kwargs,
    ):
        """Pass the schedule's start, so we can use it to validate soc-target datetimes."""
        self.start = start
        self.sensor = sensor
        self.timezone = sensor.timezone if sensor is not None else None
        # guess default soc-unit
        if default_soc_unit is None:
            if self.sensor is not None and self.sensor.unit in ("MWh", "kWh"):
                default_soc_unit = self.sensor.unit
            elif self.sensor is not None and self.sensor.unit in ("MW", "kW"):
                default_soc_unit = self.sensor.unit + "h"
            else:
                default_soc_unit = "MWh"

        super().__init__(*args, **kwargs)
        for field in self.fields.keys():
            if field.startswith("soc_"):
                # Override the class-level placeholders. Note that assigning new
                # instance-level fields would be inert (marshmallow resolves fields
                # from the class-level declared fields), so we set attributes on
                # the bound fields instead. SoC event datetimes are deliberately
                # not floored (no event_resolution is set): off-tick events are
                # preserved and later projected onto the scheduling ticks.
                setattr(self.fields[field], "timezone", self.timezone)
                if default_soc_unit is not None:
                    setattr(self.fields[field], "default_src_unit", default_soc_unit)

    @validates_schema
    def check_whether_targets_exceed_max_planning_horizon(self, data: dict, **kwargs):
        # skip check if the flex-model does not define a sensor: the StorageScheduler will not base its resolution on this flex-model
        if self.sensor is None:
            return
        soc_targets: list[SoCTarget] | Sensor | None = data.get("soc_targets")
        # skip check if the SOC targets are not provided or if they are defined as sensors
        if not soc_targets or isinstance(soc_targets, (Sensor, SensorReference)):
            return
        max_target_datetime = max([target["end"] for target in soc_targets])
        max_server_horizon = current_app.config.get("FLEXMEASURES_MAX_PLANNING_HORIZON")
        if isinstance(max_server_horizon, int):
            max_server_horizon *= self.sensor.event_resolution
        # just telling the type checker that we are sure it is a timedelta now
        max_server_horizon = cast(timedelta, max_server_horizon)
        max_server_datetime = self.start + max_server_horizon
        if max_target_datetime > max_server_datetime:
            current_app.logger.warning(
                f"Target datetime exceeds {max_server_datetime}. Maximum scheduling horizon is {max_server_horizon}."
            )

    @validates("state_of_charge")
    def validate_state_of_charge(
        self, state_of_charge: Sensor | SensorReference | list[dict], **kwargs
    ):
        if isinstance(
            state_of_charge, (Sensor, SensorReference)
        ) and state_of_charge.event_resolution != timedelta(0):
            raise ValidationError(
                "The field `state-of-charge` points to a sensor with a non-instantaneous event resolution. Please, use an instantaneous sensor."
            )
        if not isinstance(state_of_charge, (Sensor, SensorReference, list)):
            raise ValidationError(
                "The `state-of-charge` field can only be a Sensor or a time series."
            )

    @validates("group")
    def validate_group(self, group: dict, **kwargs):
        _validate_group_sensor_is_power_sensor(group)

    @validates("asset")
    def validate_asset(self, asset: Asset, **kwargs):
        if self.sensor is not None and self.sensor.asset != asset:
            raise ValidationError("Sensor does not belong to asset.")

    @validates_schema
    def validate_storage_efficiency_resolution(self, data: dict, **kwargs):
        unit = data.get("storage_efficiency")
        consumption = data.get("consumption")
        production = data.get("production")
        consumption_is_sensor = isinstance(consumption, dict) and isinstance(
            consumption.get("sensor"), (Sensor, SensorReference)
        )
        production_is_sensor = isinstance(production, dict) and isinstance(
            production.get("sensor"), (Sensor, SensorReference)
        )
        if (
            isinstance(unit, ur.Quantity)
            and not self.sensor
            and not consumption_is_sensor
            and not production_is_sensor
        ):
            raise ValidationError(
                "The storage-efficiency cannot be interpreted without a resolution. "
                "Record the storage-efficiency on a sensor instead (with a non-zero resolution) and then reference that sensor in the flex-model. "
                "Alternatively, set the consumption or production field in the flex-model to reference a sensor, "
                "and the scheduler will assume their resolution is the one to use.",
                field_name="storage-efficiency",
            )

    @validates_schema
    def check_redundant_efficiencies(self, data: dict, **kwargs):
        """
        Check that none of the following cases occurs:
            (1) flex-model contains both a round-trip efficiency and a charging efficiency
            (2) flex-model contains both a round-trip efficiency and a discharging efficiency
            (3) flex-model contains a round-trip efficiency, a charging efficiency and a discharging efficiency


        :raise: ValidationError
        """

        for field in ["charging_efficiency", "discharging_efficiency"]:
            if field in data and "roundtrip_efficiency" in data:
                raise ValidationError(
                    f"Fields `{field}` and `roundtrip_efficiency` are mutually exclusive."
                )

    @validates("commodity")
    def validate_commodity(self, commodity: str, **kwargs):
        if not isinstance(commodity, str) or not commodity.strip():
            raise ValidationError("commodity must be a non-empty string.")

    @validates("coupling")
    def validate_coupling(self, coupling: str | None, **kwargs):
        _validate_coupling_name(coupling)

    @validates_schema
    def validate_coupling_direction_is_unambiguous(self, data: dict, **kwargs):
        """A coupled device must have an inferable flow direction.

        The flow direction is inferred from which directional capacity is given:
        a device with (only) a consumption-capacity is an input (consuming) device,
        and a device with (only) a production-capacity is an output (producing)
        device. The unspecified direction is assumed to be zero, mirroring how a
        missing directional site capacity defaults to zero, so the user does not
        need to set the opposite direction to a fixed 0 (though doing so still works).

        The direction is ambiguous only when both directions are active (each side
        either flows itself or is marked active by a fixed zero on the opposite side)
        or when neither is (both missing); such flex-models are rejected.
        """
        if data.get("coupling") is None:
            return

        def _is_fixed_zero(value) -> bool:
            return isinstance(value, ur.Quantity) and float(value.magnitude) == 0.0

        def _flows(value) -> bool:
            # A capacity flows when it is given and not a fixed zero.
            # Sensor references cannot be checked statically, so they flow.
            return value is not None and not _is_fixed_zero(value)

        consumption = data.get("consumption_capacity")
        production = data.get("production_capacity")
        # A direction is active if it flows itself, or if the opposite direction is
        # explicitly pinned to zero (the legacy way of marking a direction).
        consumption_active = _flows(consumption) or _is_fixed_zero(production)
        production_active = _flows(production) or _is_fixed_zero(consumption)
        if consumption_active == production_active:
            raise ValidationError(
                "A device with a 'coupling' field must have an unambiguous flow direction: "
                "provide exactly one directional capacity, either a consumption-capacity "
                "(for an input/consuming device) or a production-capacity (for an "
                "output/producing device). The opposite direction defaults to zero.",
                field_name="coupling",
            )

    @post_load
    def post_load_sequence(self, data: dict, **kwargs) -> dict:
        """Perform some checks and corrections after we loaded."""
        # currently we only handle MWh internally, and the conversion to MWh happened during deserialization
        data["soc_unit"] = "MWh"

        # Convert efficiency to dimensionless (to the (0,1] range)
        if data.get("roundtrip_efficiency") is not None:
            data["roundtrip_efficiency"] = (
                data["roundtrip_efficiency"].to(ur.Quantity("dimensionless")).magnitude
            )

        # Convert soc_at_start to dimensionless
        if data.get("soc_at_start") is not None:
            data["soc_at_start"] = (data["soc_at_start"] / ur.Quantity("MWh")).magnitude

        # Convert soc_min to dimensionless
        if data.get("soc_min") is not None:
            data["soc_min"] = (data["soc_min"] / ur.Quantity("MWh")).magnitude
        # Convert soc_max to dimensionless
        if data.get("soc_max") is not None:
            data["soc_max"] = (data["soc_max"] / ur.Quantity("MWh")).magnitude

        return data


class DBStorageFlexModelSchema(Schema):
    """
    Schema for flex-models stored in the db. Supports fixed quantities and sensor references, while disallowing time series specs.
    """

    consumption = fields.Nested(OutputSensorReferenceSchema)
    production = fields.Nested(OutputSensorReferenceSchema)

    group = fields.Nested(
        GroupReferenceSchema,
        data_key="group",
        required=False,
        metadata=metadata.GROUP.to_dict(),
    )

    soc_min = VariableQuantityField(
        to_unit="MWh",
        data_key="soc-min",
        required=False,
        value_validator=validate.Range(min=0),
        metadata={"deprecated field": "min_soc_in_mwh"},
    )

    soc_max = VariableQuantityField(
        to_unit="MWh",
        data_key="soc-max",
        required=False,
        value_validator=validate.Range(min=0),
        metadata={"deprecated field": "max_soc_in_mwh"},
    )

    soc_minima = VariableQuantityField(
        to_unit="MWh",
        data_key="soc-minima",
        required=False,
        value_validator=validate.Range(min=0),
    )

    soc_maxima = VariableQuantityField(
        to_unit="MWh",
        data_key="soc-maxima",
        required=False,
        value_validator=validate.Range(min=0),
    )

    soc_targets = VariableQuantityField(
        to_unit="MWh",
        data_key="soc-targets",
        required=False,
        value_validator=validate.Range(min=0),
    )

    state_of_charge = VariableQuantityField(
        to_unit="MWh",
        data_key="state-of-charge",
        required=False,
        value_validator=validate.Range(min=0),
        additional_sensor_units=["%"],
    )

    soc_gain = fields.List(
        VariableQuantityField("MW"),
        data_key="soc-gain",
        required=False,
        validate=validate.Length(min=1),
        metadata={"deprecated field": "soc-gain"},
    )

    soc_usage = fields.List(
        VariableQuantityField("MW"),
        data_key="soc-usage",
        required=False,
        validate=validate.Length(min=1),
        metadata={"deprecated field": "soc-usage"},
    )

    roundtrip_efficiency = EfficiencyField(
        data_key="roundtrip-efficiency",
        required=False,
        metadata={"deprecated field": "roundtrip_efficiency"},
    )

    charging_efficiency = VariableQuantityField(
        "%",
        data_key="charging-efficiency",
        required=False,
        metadata={"deprecated field": "charging-efficiency"},
    )

    discharging_efficiency = VariableQuantityField(
        "%",
        data_key="discharging-efficiency",
        required=False,
        metadata={"deprecated field": "discharging-efficiency"},
    )

    storage_efficiency = VariableQuantityField(
        "%",
        data_key="storage-efficiency",
        required=False,
        metadata={"deprecated field": "storage_efficiency"},
    )

    prefer_charging_sooner = fields.Bool(
        data_key="prefer-charging-sooner", load_default=True
    )

    prefer_curtailing_later = fields.Bool(
        data_key="prefer-curtailing-later", load_default=True
    )

    power_capacity = VariableQuantityField(
        to_unit="MW",
        data_key="power-capacity",
        required=False,
        value_validator=validate.Range(min=0),
        metadata={"deprecated field": "capacity_in_mw"},
    )

    consumption_capacity = VariableQuantityField(
        to_unit="MW",
        data_key="consumption-capacity",
        required=False,
        value_validator=validate.Range(min=0),
        metadata={"deprecated field": "consumption_capacity"},
    )

    production_capacity = VariableQuantityField(
        to_unit="MW",
        data_key="production-capacity",
        required=False,
        value_validator=validate.Range(min=0),
        metadata={"deprecated field": "production_capacity"},
    )

    commodity = fields.Str(
        required=False,
        data_key="commodity",
        load_default="electricity",
        validate=OneOf(["electricity", "gas"]),
        metadata=dict(description="Commodity label for this device/asset."),
    )

    coupling = fields.Str(
        data_key="coupling",
        required=False,
        load_default=None,
        metadata=metadata.COUPLING.to_dict(),
    )

    coupling_coefficient = fields.Float(
        data_key="coupling-coefficient",
        required=False,
        load_default=1.0,
        validate=validate.Range(min=0, min_inclusive=False),
        metadata=metadata.COUPLING_COEFFICIENT.to_dict(),
    )

    coupling_base = QuantityField(
        "MW",
        data_key="coupling-base",
        required=False,
        validate=validate.Range(min=ur.Quantity("0 MW")),
        metadata=metadata.COUPLING_BASE.to_dict(),
    )

    coupling_min = QuantityField(
        "MW",
        data_key="coupling-min",
        required=False,
        validate=validate.Range(min=ur.Quantity("0 MW")),
        metadata=metadata.COUPLING_MIN.to_dict(),
    )

    mapped_schema_keys: dict

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize mapped_schema_keys to map field names to their data keys
        # This is necessary for validation methods to access the correct data keys
        # after the schema is declared.
        self.mapped_schema_keys = {
            field: (self.declared_fields[field].data_key or field)
            for field in self.declared_fields
        }

    @validates("group")
    def validate_group(self, group: dict, **kwargs):
        _validate_group_sensor_is_power_sensor(group)

    @validates("coupling")
    def validate_coupling(self, coupling: str | None, **kwargs):
        _validate_coupling_name(coupling)

    @validates_schema
    def forbid_time_series_specs(self, data: dict, **kwargs):
        """Do not allow time series specs for the flex-model fields saved in the db."""

        # List of keys to check for time series specs
        keys_to_check = []
        # All the keys in this list are all fields of type VariableQuantity
        for field_var, field in self.declared_fields.items():
            if isinstance(field, VariableQuantityField):
                keys_to_check.append((field_var, field))

        # Check each key and raise a ValidationError if it's a list
        for field_var, field in keys_to_check:
            if field_var in data and isinstance(data[field_var], list):
                raise ValidationError(
                    "A time series specification (listing segments) is not supported when storing flex-model fields. Use a fixed quantity or a sensor reference instead.",
                    field_name=field.data_key,
                )

    @validates_schema
    def validate_fields_unit(self, data: dict, **kwargs):
        """Check that each field value has a valid unit."""

        self._validate_energy_fields(data)
        self._validate_power_fields(data)
        self._validate_array_fields(data)

    def _validate_energy_fields(self, data: dict):
        """Validate energy fields."""
        energy_fields = [
            "soc_min",
            "soc_max",
            "soc_minima",
            "soc_maxima",
            "soc_targets",
        ]

        for field in energy_fields:
            if field in data:
                self._validate_field(data, field, unit_validator=is_energy_unit)

        # state_of_charge sensors may use an energy unit or '%'
        if "state_of_charge" in data:
            self._validate_field(
                data,
                "state_of_charge",
                unit_validator=lambda u: is_energy_unit(u) or u == "%",
            )

    def _validate_power_fields(self, data: dict):
        """Validate power fields."""
        power_fields = [
            "power_capacity",
            "consumption_capacity",
            "production_capacity",
        ]

        for field in power_fields:
            if field in data:
                self._validate_field(data, field, unit_validator=is_power_unit)

    def _validate_array_fields(self, data: dict):
        """Validate power array fields."""
        array_fields = ["soc_gain", "soc_usage"]

        if self.mapped_schema_keys is None:
            raise ValueError(
                "mapped_schema_keys must be initialized before validation."
            )

        for field in array_fields:
            if field in data:
                for item in data[field]:
                    if isinstance(item, ur.Quantity):
                        if not is_power_unit(str(item.units)):
                            raise ValidationError(
                                f"Field '{self.mapped_schema_keys[field]}' must have a power unit.",
                                field_name=self.mapped_schema_keys[field],
                            )
                    elif isinstance(item, (Sensor, SensorReference)):
                        if not is_power_unit(item.unit):
                            raise ValidationError(
                                f"Field '{self.mapped_schema_keys[field]}' must have a power unit.",
                                field_name=self.mapped_schema_keys[field],
                            )
                    else:
                        raise ValidationError(
                            f"Field '{self.mapped_schema_keys[field]}' must be a list of quantities or sensors.",
                            field_name=self.mapped_schema_keys[field],
                        )

    def _validate_field(self, data: dict, field: str, unit_validator: Callable):
        """Validate fields based on type and unit validator."""

        if self.mapped_schema_keys is None:
            raise ValueError(
                "mapped_schema_keys must be initialized before validation."
            )

        if isinstance(data[field], ur.Quantity):
            if not unit_validator(str(data[field].units)):
                raise ValidationError(
                    f"Field '{self.mapped_schema_keys[field]}' failed unit validation by {unit_validator.__name__}.",
                    field_name=self.mapped_schema_keys[field],
                )
        elif isinstance(data[field], (Sensor, SensorReference)):
            if not unit_validator(data[field].unit):
                raise ValidationError(
                    f"Field '{self.mapped_schema_keys[field]}' failed unit validation by {unit_validator.__name__}.",
                    field_name=self.mapped_schema_keys[field],
                )
