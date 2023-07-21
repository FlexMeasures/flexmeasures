from __future__ import annotations

from datetime import datetime
import pytz
import pandas as pd

from marshmallow import (
    Schema,
    post_load,
    fields,
    pre_load,
)

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.times import (
    DurationField,
    TimeIntervalSchema,
)


from flexmeasures.data.schemas.sensors import SensorIdField

from enum import Enum


class LoadType(Enum):
    INFLEXIBLE = "INFLEXIBLE"
    BREAKABLE = "BREAKABLE"
    SHIFTABLE = "SHIFTABLE"


class OptimizationSense(Enum):
    MAX = "MAX"
    MIN = "MIN"


class ShiftableLoadFlexModelSchema(Schema):
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    duration = DurationField(required=True)
    power = fields.Float(required=True)

    load_type = fields.Enum(
        LoadType, load_default=LoadType.INFLEXIBLE, data_key="load-type"
    )
    time_restrictions = fields.List(
        fields.Nested(TimeIntervalSchema()),
        data_key="time-restrictions",
        load_default=[],
    )
    optimization_sense = fields.Enum(
        OptimizationSense,
        load_default=OptimizationSense.MIN,
        data_key="optimization-sense",
    )

    def __init__(self, sensor: Sensor, start: datetime, end: datetime, *args, **kwargs):
        """Pass start and end to convert time_restrictions into a time series and sensor
        as a fallback mechanism for the load_type
        """
        self.start = start.astimezone(pytz.utc)
        self.end = end.astimezone(pytz.utc)
        self.sensor = sensor
        super().__init__(*args, **kwargs)

    def get_mask_from_events(self, events: list[dict[str, str]] | None) -> pd.Series:
        """Convert events to a mask of the time periods that are valid

        :param events: list of events defined as dictionaries with a start and duration
        :return: mask of the allowed time periods
        """
        series = pd.Series(
            index=pd.date_range(
                self.start,
                self.end,
                freq=self.sensor.event_resolution,
                inclusive="left",
                name="event_start",
                tz=self.start.tzinfo,
            ),
            data=False,
        )

        if events is None:
            return series

        for event in events:
            start = event["start"]
            duration = event["duration"]
            end = start + duration
            series[(series.index >= start) & (series.index < end)] = True

        return series

    @post_load
    def post_load_time_restrictions(self, data: dict, **kwargs) -> dict:
        """Convert events (list of [start, duration] pairs) into a mask (pandas Series)"""

        data["time_restrictions"] = self.get_mask_from_events(data["time_restrictions"])

        return data

    @pre_load
    def pre_load_load_type(self, data: dict, **kwargs) -> dict:
        """Fallback mechanism for the load_type variable. If not found in data,
        it tries to find it in among the sensor attributes and, if it's not found
        there either, it defaults to "INFLEXIBLE".
        """
        if "load-type" not in data or data["load-type"] is None:
            load_type = self.sensor.get_attribute("load_type")

            if load_type is None:
                load_type = "INFLEXIBLE"

            data["load-type"] = load_type

        return data
