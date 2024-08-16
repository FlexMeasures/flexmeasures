from __future__ import annotations

from datetime import datetime

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

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.sensors import VariableQuantityField

from flexmeasures.utils.unit_utils import ur


class EfficiencyField(QuantityField):
    """Field that deserializes to a Quantity with % units. Must be greater than 0% and less than or equal to 100%.

    Examples:

        >>> ef = EfficiencyField()
        >>> ef.deserialize(0.9)
        <Quantity(90.0, 'percent')>
        >>> ef.deserialize("90%")
        <Quantity(90.0, 'percent')>
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

    soc_at_start = QuantityField(
        required=True,
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

    charging_efficiency = VariableQuantityField(
        "%", data_key="charging-efficiency", required=False
    )
    discharging_efficiency = VariableQuantityField(
        "%", data_key="discharging-efficiency", required=False
    )

    roundtrip_efficiency = EfficiencyField(
        data_key="roundtrip-efficiency", required=False
    )

    storage_efficiency = VariableQuantityField(
        "%", default_src_unit="dimensionless", data_key="storage-efficiency"
    )
    prefer_charging_sooner = fields.Bool(data_key="prefer-charging-sooner")

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
        sensor: Sensor,
        *args,
        default_soc_unit: str | None = None,
        **kwargs,
    ):
        """Pass the schedule's start, so we can use it to validate soc-target datetimes."""
        self.start = start
        self.sensor = sensor

        # guess default soc-unit
        if default_soc_unit is None:
            if self.sensor.unit in ("MWh", "kWh"):
                default_soc_unit = self.sensor.unit
            elif self.sensor.unit in ("MW", "kW"):
                default_soc_unit = self.sensor.unit + "h"

        self.soc_maxima = VariableQuantityField(
            to_unit="MWh",
            default_src_unit=default_soc_unit,
            timezone=sensor.timezone,
            data_key="soc-maxima",
        )

        self.soc_minima = VariableQuantityField(
            to_unit="MWh",
            default_src_unit=default_soc_unit,
            timezone=sensor.timezone,
            data_key="soc-minima",
            value_validator=validate.Range(min=0),
        )
        self.soc_targets = VariableQuantityField(
            to_unit="MWh",
            default_src_unit=default_soc_unit,
            timezone=sensor.timezone,
            data_key="soc-targets",
        )

        super().__init__(*args, **kwargs)
        if default_soc_unit is not None:
            for field in self.fields.keys():
                if field.startswith("soc_"):
                    setattr(self.fields[field], "default_src_unit", default_soc_unit)

    @validates_schema
    def check_whether_targets_exceed_max_planning_horizon(self, data: dict, **kwargs):
        soc_targets: list[dict[str, datetime | float] | Sensor] | None = data.get(
            "soc_targets"
        )
        # skip check if the SOC targets are not provided or if they are defined as sensors
        if not soc_targets or isinstance(soc_targets, Sensor):
            return
        max_server_horizon = current_app.config.get("FLEXMEASURES_MAX_PLANNING_HORIZON")
        if isinstance(max_server_horizon, int):
            max_server_horizon *= self.sensor.event_resolution
        max_target_datetime = max([target["end"] for target in soc_targets])
        max_server_datetime = self.start + max_server_horizon
        if max_target_datetime > max_server_datetime:
            current_app.logger.warning(
                f"Target datetime exceeds {max_server_datetime}. Maximum scheduling horizon is {max_server_horizon}."
            )

    @validates("storage_efficiency")
    def validate_storage_efficiency_resolution(self, unit: Sensor | ur.Quantity):
        if (
            isinstance(unit, Sensor)
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
