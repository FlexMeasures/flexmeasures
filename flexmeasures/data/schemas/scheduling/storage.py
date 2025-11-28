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
from flexmeasures.data.schemas.sensors import VariableQuantityField
from flexmeasures.utils.unit_utils import (
    ur,
    is_power_unit,
    is_energy_unit,
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
    """Field that deserializes to a Quantity with % units. Must be greater than 0% and less than or equal to 100%.

    Examples:

        >>> ef = EfficiencyField()
        >>> ef.deserialize(0.9)
        <Quantity(90.0, 'percent')>
        >>> ef.deserialize("90%")
        <Quantity(90, 'percent')>
        >>> ef.deserialize("0%")
        Traceback (most recent call last):
        ...
        marshmallow.exceptions.ValidationError: ['Must be greater than 0 and less than or equal to 1.']
    """

    def __init__(self, *args, **kwargs):
        super().__init__(
            "%",
            validate=validate.Range(
                min=0, max=1, min_inclusive=False, max_inclusive=True
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

    asset = GenericAssetIdField(required=False)

    soc_at_start = QuantityField(
        required=False,
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=True,
        data_key="soc-at-start",
    )

    soc_min = QuantityField(
        validate=validate.Range(
            min=0
        ),  # change to min=ur.Quantity("0 MWh") in case return_magnitude=False
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=True,
        data_key="soc-min",
    )
    soc_max = QuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        return_magnitude=True,
        data_key="soc-max",
    )

    power_capacity_in_mw = VariableQuantityField(
        "MW", required=False, data_key="power-capacity"
    )

    consumption_capacity = VariableQuantityField(
        "MW", data_key="consumption-capacity", required=False
    )
    production_capacity = VariableQuantityField(
        "MW", data_key="production-capacity", required=False
    )

    # Activation prices
    prefer_curtailing_later = fields.Bool(
        data_key="prefer-curtailing-later", load_default=True
    )
    prefer_charging_sooner = fields.Bool(
        data_key="prefer-charging-sooner", load_default=True
    )

    # Timezone placeholders for the soc_maxima, soc_minima and soc_targets fields are overridden in __init__
    soc_maxima = VariableQuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        timezone="placeholder",
        data_key="soc-maxima",
    )

    soc_minima = VariableQuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        timezone="placeholder",
        data_key="soc-minima",
        value_validator=validate.Range(min=0),
    )

    soc_targets = VariableQuantityField(
        to_unit="MWh",
        default_src_unit="dimensionless",  # placeholder, overridden in __init__
        timezone="placeholder",
        data_key="soc-targets",
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
    )

    state_of_charge = VariableQuantityField(
        to_unit="MWh",
        data_key="state-of-charge",
        required=False,
    )

    charging_efficiency = VariableQuantityField(
        "%", data_key="charging-efficiency", required=False
    )
    discharging_efficiency = VariableQuantityField(
        "%", data_key="discharging-efficiency", required=False
    )

    roundtrip_efficiency = EfficiencyField(
        data_key="roundtrip-efficiency", required=False
    )

    storage_efficiency = VariableQuantityField("%", data_key="storage-efficiency")

    soc_gain = fields.List(
        VariableQuantityField("MW"),
        data_key="soc-gain",
        required=False,
        validate=validate.Length(min=1),
    )
    soc_usage = fields.List(
        VariableQuantityField("MW"),
        data_key="soc-usage",
        required=False,
        validate=validate.Length(min=1),
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

        self.soc_maxima = VariableQuantityField(
            to_unit="MWh",
            default_src_unit=default_soc_unit,
            timezone=self.timezone,
            data_key="soc-maxima",
        )

        self.soc_minima = VariableQuantityField(
            to_unit="MWh",
            default_src_unit=default_soc_unit,
            timezone=self.timezone,
            data_key="soc-minima",
            value_validator=validate.Range(min=0),
        )
        self.soc_targets = VariableQuantityField(
            to_unit="MWh",
            default_src_unit=default_soc_unit,
            timezone=self.timezone,
            data_key="soc-targets",
        )

        super().__init__(*args, **kwargs)
        if default_soc_unit is not None:
            for field in self.fields.keys():
                if field.startswith("soc_"):
                    setattr(self.fields[field], "default_src_unit", default_soc_unit)

    @validates_schema
    def check_whether_targets_exceed_max_planning_horizon(self, data: dict, **kwargs):
        # skip check if the flex-model does not define a sensor: the StorageScheduler will not base its resolution on this flex-model
        if self.sensor is None:
            return
        soc_targets: list[SoCTarget] | Sensor | None = data.get("soc_targets")
        # skip check if the SOC targets are not provided or if they are defined as sensors
        if not soc_targets or isinstance(soc_targets, Sensor):
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
    def validate_state_of_charge_is_sensor(
        self, state_of_charge: Sensor | list[dict] | ur.Quantity, **kwargs
    ):
        if not isinstance(state_of_charge, Sensor):
            raise ValidationError(
                "The `state-of-charge` field can only be a Sensor. In the future, the state-of-charge field will replace soc-at-start field."
            )

        if state_of_charge.event_resolution != timedelta(0):
            raise ValidationError(
                "The field `state-of-charge` points to a sensor with a non-instantaneous event resolution. Please, use an instantaneous sensor."
            )

    @validates("asset")
    def validate_asset(self, asset: Asset, **kwargs):
        if self.sensor is not None and self.sensor.asset != asset:
            raise ValidationError("Sensor does not belong to asset.")

    @validates("storage_efficiency")
    def validate_storage_efficiency_resolution(
        self, unit: Sensor | ur.Quantity, **kwargs
    ):
        if (
            self.sensor is not None
            and isinstance(unit, Sensor)
            and unit.event_resolution != self.sensor.event_resolution
        ):
            raise ValidationError(
                "Event resolution of the storage efficiency and the power sensor don't match. Resampling the storage efficiency is not supported."
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

        return data


class DBStorageFlexModelSchema(Schema):
    """
    Schema for flex-models stored in the db. Supports fixed quantities and sensor references, while disallowing time series specs.
    """

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

    storage_efficiency = EfficiencyField(
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
            "state_of_charge",
        ]

        for field in energy_fields:
            if field in data:
                self._validate_field(data, field, unit_validator=is_energy_unit)

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
                    elif isinstance(item, Sensor):
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
        elif isinstance(data[field], Sensor):
            if not unit_validator(data[field].unit):
                raise ValidationError(
                    f"Field '{self.mapped_schema_keys[field]}' failed unit validation by {unit_validator.__name__}.",
                    field_name=self.mapped_schema_keys[field],
                )
