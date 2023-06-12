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
from marshmallow.validate import OneOf

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.schemas.units import QuantityField
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
    """
    A point in time with a target value.
    """

    value = fields.Float(required=True)
    datetime = AwareDateTimeField(required=True)

    def __init__(self, *args, **kwargs):
        self.value_validator = kwargs.pop("value_validator", None)
        super().__init__(*args, **kwargs)

    @validates("value")
    def validate_value(self, _value):

        if self.value_validator is not None:
            self.value_validator(_value)


class StorageFlexModelSchema(Schema):
    """
    This schema lists fields we require when scheduling storage assets.
    Some fields are not required, as they might live on the Sensor.attributes.
    You can use StorageScheduler.deserialize_flex_config to get that filled in.
    """

    soc_at_start = fields.Float(required=True, data_key="soc-at-start")

    soc_min = fields.Float(validate=validate.Range(min=0), data_key="soc-min")
    soc_max = fields.Float(data_key="soc-max")

    soc_maxima = fields.List(fields.Nested(SOCValueSchema()), data_key="soc-maxima")
    soc_minima = fields.List(
        fields.Nested(SOCValueSchema(value_validator=validate.Range(min=0))),
        data_key="soc-minima",
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
    soc_targets = fields.List(fields.Nested(SOCValueSchema()), data_key="soc-targets")
    roundtrip_efficiency = EfficiencyField(data_key="roundtrip-efficiency")
    storage_efficiency = EfficiencyField(data_key="storage-efficiency")
    prefer_charging_sooner = fields.Bool(data_key="prefer-charging-sooner")

    def __init__(self, start: datetime, sensor: Sensor, *args, **kwargs):
        """Pass the schedule's start, so we can use it to validate soc-target datetimes."""
        self.start = start
        self.sensor = sensor
        super().__init__(*args, **kwargs)

    @validates_schema
    def check_whether_targets_exceed_max_planning_horizon(self, data: dict, **kwargs):
        soc_targets: list[dict[str, datetime | float]] | None = data.get("soc_targets")
        if not soc_targets:
            return
        max_server_horizon = current_app.config.get("FLEXMEASURES_MAX_PLANNING_HORIZON")
        if isinstance(max_server_horizon, int):
            max_server_horizon *= self.sensor.event_resolution
        max_target_datetime = max([target["datetime"] for target in soc_targets])
        max_server_datetime = self.start + max_server_horizon
        if max_target_datetime > max_server_datetime:
            current_app.logger.warning(
                f"Target datetime exceeds {max_server_datetime}. Maximum scheduling horizon is {max_server_horizon}."
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
            data["soc_unit"] = "MWh"

        # Convert efficiencies to dimensionless (to the (0,1] range)
        efficiency_fields = ("storage_efficiency", "roundtrip_efficiency")
        for field in efficiency_fields:
            if data.get(field) is not None:
                data[field] = data[field].to(ur.Quantity("dimensionless")).magnitude

        return data
