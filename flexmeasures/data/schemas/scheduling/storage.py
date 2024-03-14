from __future__ import annotations

from datetime import datetime

import isodate
from flask import current_app
from marshmallow import (
    Schema,
    post_load,
    validate,
    validates_schema,
    fields,
    validates,
)
from marshmallow.validate import OneOf, ValidationError, Validator
import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.sensors import QuantityOrSensor

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


class SOCValueSchema(Schema):
    value = fields.Float(required=True)
    datetime = AwareDateTimeField(required=False)
    start = AwareDateTimeField(required=False)
    end = AwareDateTimeField(required=False)
    duration = DurationField(required=False)

    def __init__(
        self,
        timezone: str | None = None,
        value_validator: Validator | None = None,
        *args,
        **kwargs,
    ):
        """A time period (or single point) with a target value.

        :param timezone:  Optionally, set a timezone to be able to interpret nominal durations.
        """
        self.timezone = timezone
        self.value_validator = value_validator
        super().__init__(*args, **kwargs)

    @validates("value")
    def validate_value(self, _value):
        if self.value_validator is not None:
            self.value_validator(_value)

    @validates_schema
    def check_time_window(self, data: dict, **kwargs):
        """Checks whether a complete time interval can be derived from the timing fields.

        The data is updated in-place, guaranteeing that the 'start' and 'end' fields are filled out.
        """
        dt = data.get("datetime")
        start = data.get("start")
        end = data.get("end")
        duration = data.get("duration")

        if dt is not None:
            if any([p is not None for p in (start, end, duration)]):
                raise ValidationError(
                    "If using the 'datetime' field, no 'start', 'end' or 'duration' is expected."
                )
            data["start"] = dt
            data["end"] = dt
        elif duration is not None:
            if self.timezone is None and isinstance(duration, isodate.Duration):
                raise ValidationError(
                    "Cannot interpret nominal duration used in the 'duration' field without a known timezone."
                )
            elif all([p is None for p in (start, end)]) or all(
                [p is not None for p in (start, end)]
            ):
                raise ValidationError(
                    "If using the 'duration' field, either 'start' or 'end' is expected."
                )
            if start is not None:
                grounded = DurationField.ground_from(
                    duration, pd.Timestamp(start).tz_convert(self.timezone)
                )
                data["start"] = start
                data["end"] = start + grounded
            else:
                grounded = DurationField.ground_from(
                    -duration, pd.Timestamp(end).tz_convert(self.timezone)
                )
                data["start"] = end + grounded
                data["end"] = end
        else:
            if any([p is None for p in (start, end)]):
                raise ValidationError(
                    "Missing field(s) to describe timing: use the 'datetime' field, "
                    "or a combination of 2 fields of 'start', 'end' and 'duration'."
                )
            data["start"] = start
            data["end"] = end


class StorageFlexModelSchema(Schema):
    """
    This schema lists fields we require when scheduling storage assets.
    Some fields are not required, as they might live on the Sensor.attributes.
    You can use StorageScheduler.deserialize_flex_config to get that filled in.
    """

    soc_at_start = fields.Float(required=True, data_key="soc-at-start")

    soc_min = fields.Float(validate=validate.Range(min=0), data_key="soc-min")
    soc_max = fields.Float(data_key="soc-max")

    power_capacity_in_mw = QuantityOrSensor(
        "MW", required=False, data_key="power-capacity"
    )

    consumption_capacity = QuantityOrSensor(
        "MW", data_key="consumption-capacity", required=False
    )
    production_capacity = QuantityOrSensor(
        "MW", data_key="production-capacity", required=False
    )

    # Timezone placeholder is overridden in __init__
    soc_maxima = fields.List(
        fields.Nested(SOCValueSchema(timezone="placeholder")),
        data_key="soc-maxima",
    )
    soc_minima = fields.List(
        fields.Nested(
            SOCValueSchema(
                timezone="placeholder", value_validator=validate.Range(min=0)
            )
        ),
        data_key="soc-minima",
    )
    soc_targets = fields.List(
        fields.Nested(SOCValueSchema(timezone="placeholder")),
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
    )  # todo: allow unit to be set per field, using QuantityField("%", validate=validate.Range(min=0, max=1))

    charging_efficiency = QuantityOrSensor(
        "%", data_key="charging-efficiency", required=False
    )
    discharging_efficiency = QuantityOrSensor(
        "%", data_key="discharging-efficiency", required=False
    )

    roundtrip_efficiency = EfficiencyField(
        data_key="roundtrip-efficiency", required=False
    )

    storage_efficiency = QuantityOrSensor(
        "%", default_src_unit="dimensionless", data_key="storage-efficiency"
    )
    prefer_charging_sooner = fields.Bool(data_key="prefer-charging-sooner")

    soc_gain = fields.List(QuantityOrSensor("MW"), data_key="soc-gain", required=False)
    soc_usage = fields.List(
        QuantityOrSensor("MW"), data_key="soc-usage", required=False
    )

    def __init__(self, start: datetime, sensor: Sensor, *args, **kwargs):
        """Pass the schedule's start, so we can use it to validate soc-target datetimes."""
        self.start = start
        self.sensor = sensor
        self.soc_maxima = fields.List(
            fields.Nested(SOCValueSchema(timezone=sensor.timezone)),
            data_key="soc-maxima",
        )
        self.soc_minima = fields.List(
            fields.Nested(
                SOCValueSchema(
                    timezone=sensor.timezone, value_validator=validate.Range(min=0)
                )
            ),
            data_key="soc-minima",
        )
        self.soc_targets = fields.List(
            fields.Nested(SOCValueSchema(timezone=sensor.timezone)),
            data_key="soc-targets",
        )
        super().__init__(*args, **kwargs)

    @validates_schema
    def check_whether_targets_exceed_max_planning_horizon(self, data: dict, **kwargs):
        soc_targets: list[dict[str, datetime | float]] | None = data.get("soc_targets")
        if not soc_targets:
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
        # currently we only handle MWh internally
        # TODO: review when we moved away from capacity having to be described in MWh
        if data.get("soc_unit") == "kWh":
            data["soc_at_start"] /= 1000.0
            if data.get("soc_min") is not None:
                data["soc_min"] /= 1000.0
            if data.get("soc_max") is not None:
                data["soc_max"] /= 1000.0
            if data.get("soc_targets"):
                for target in data["soc_targets"]:
                    target["value"] /= 1000.0
            if data.get("soc_minima"):
                for minimum in data["soc_minima"]:
                    minimum["value"] /= 1000.0
            if data.get("soc_maxima"):
                for maximum in data["soc_maxima"]:
                    maximum["value"] /= 1000.0
            data["soc_unit"] = "MWh"

        # Convert efficiency to dimensionless (to the (0,1] range)
        if data.get("roundtrip_efficiency") is not None:
            data["roundtrip_efficiency"] = (
                data["roundtrip_efficiency"].to(ur.Quantity("dimensionless")).magnitude
            )

        return data
