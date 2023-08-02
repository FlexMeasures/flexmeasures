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


from enum import Enum


class ProcessType(Enum):
    INFLEXIBLE = "INFLEXIBLE"
    BREAKABLE = "BREAKABLE"
    SHIFTABLE = "SHIFTABLE"


class OptimizationDirection(Enum):
    MAX = "MAX"
    MIN = "MIN"


class ProcessSchedulerFlexModelSchema(Schema):
    # time that the process last.
    duration = DurationField(required=True)
    # nominal power of the process.
    power = fields.Float(required=True)
    # policy to schedule a process: INFLEXIBLE, SHIFTABLE, BREAKABLE
    process_type = fields.Enum(
        ProcessType, load_default=ProcessType.INFLEXIBLE, data_key="process-type"
    )
    # time_restrictions will be turned into a Series with Boolean values (where True means restricted for scheduling).
    time_restrictions = fields.List(
        fields.Nested(TimeIntervalSchema()),
        data_key="time-restrictions",
        load_default=[],
    )
    # objective of the scheduler, to maximize or minimize.
    optimization_direction = fields.Enum(
        OptimizationDirection,
        load_default=OptimizationDirection.MIN,
        data_key="optimization-sense",
    )

    def __init__(self, sensor: Sensor, start: datetime, end: datetime, *args, **kwargs):
        """Pass start and end to convert time_restrictions into a time series and sensor
        as a fallback mechanism for the process_type
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
    def pre_load_process_type(self, data: dict, **kwargs) -> dict:
        """Fallback mechanism for the process_type variable. If not found in data,
        it tries to find it in among the sensor or asset attributes and, if it's not found
        there either, it defaults to "INFLEXIBLE".
        """
        if "process-type" not in data or data["process-type"] is None:
            process_type = self.sensor.get_attribute("process-type")

            if process_type is None:
                process_type = self.sensor.generic_asset.get_attribute("process-type")

            if process_type is None:
                process_type = "INFLEXIBLE"

            data["process-type"] = process_type

        return data
