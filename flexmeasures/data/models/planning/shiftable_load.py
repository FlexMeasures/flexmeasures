from __future__ import annotations

from math import ceil
from datetime import timedelta
import pytz

import pandas as pd

from flask import current_app

from flexmeasures.data.models.planning import Scheduler

from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.scheduling.shiftable_load import (
    ShiftableLoadFlexModelSchema,
    LoadType,
    OptimizationSense,
)
from flexmeasures.data.schemas.scheduling import FlexContextSchema


class ShiftableLoadScheduler(Scheduler):

    __version__ = "1"
    __author__ = "Seita"

    def compute(self) -> pd.Series | None:
        if not self.config_deserialized:
            self.deserialize_config()

        start = self.start.astimezone(pytz.utc)
        end = self.end.astimezone(pytz.utc)
        resolution = self.resolution
        belief_time = self.belief_time
        sensor = self.sensor

        cost_sensor: Sensor = self.flex_model.get("cost_sensor")
        duration: timedelta = self.flex_model.get("duration")
        power = self.flex_model.get("power")
        optimization_sense = self.flex_model.get("optimization_sense")
        load_type: LoadType = self.flex_model.get("load_type")
        time_restrictions = self.flex_model.get("time_restrictions")

        cost = cost_sensor.search_beliefs(
            event_starts_after=start,
            event_ends_before=end,
            resolution=resolution,
            one_deterministic_belief_per_event=True,
            beliefs_before=belief_time,
        )
        cost = simplify_index(cost)

        # Create an empty schedule
        schedule = pd.Series(
            index=pd.date_range(
                start,
                end,
                freq=sensor.event_resolution,
                closed="left",
                name="event_start",
            ),
            data=0,
            name="event_value",
        )

        # Optimize schedule for tomorrow. We can fill len(schedule) rows, at most.
        rows_to_fill = min(ceil(duration / cost_sensor.event_resolution), len(schedule))

        if rows_to_fill > len(schedule):
            current_app.logger.warning(
                f"Duration of the period exceeds the schedule window. The resulting schedule will be trimmed to fit the planning window ({start}, {end})."
            )

        assert rows_to_fill >= 1, ""

        if load_type in [LoadType.INFLEXIBLE, LoadType.SHIFTABLE]:
            # get start time instants that are not feasible, i.e, some time during the ON period goes through
            # a time restriction interval.
            time_restrictions = (
                time_restrictions.rolling(duration).max().shift(-rows_to_fill + 1)
            )
            time_restrictions = (time_restrictions == 1) | time_restrictions.isna()

            if time_restrictions.sum() == len(time_restrictions):
                raise ValueError(
                    "Cannot allocate a block of time {duration} given the time restrictions provided."
                )
        else:  # LoadType.BREAKABLE
            if (~time_restrictions).sum() < rows_to_fill:
                raise ValueError(
                    "Cannot allocate a block of time {duration} given the time restrictions provided."
                )

        if load_type == LoadType.INFLEXIBLE:
            start = time_restrictions[~time_restrictions].index[0]

            # Schedule as early as possible
            schedule.loc[
                start : start + sensor.event_resolution * (rows_to_fill - 1)
            ] = power

        elif load_type == LoadType.BREAKABLE:
            cost = cost[~time_restrictions].reset_index()

            if optimization_sense == OptimizationSense.MIN:
                cost_ranking = cost.sort_values(
                    by=["event_value", "event_start"], ascending=[True, True]
                )
            else:
                cost_ranking = cost.sort_values(
                    by=["event_value", "event_start"], ascending=[False, True]
                )

            # Break up schedule and divide it over the cleanest time slots
            schedule.loc[cost_ranking.head(rows_to_fill).event_start] = power

        elif load_type == LoadType.SHIFTABLE:
            block_cost = simplify_index(
                cost.rolling(rows_to_fill).sum().shift(-rows_to_fill + 1)
            )

            if optimization_sense == OptimizationSense.MIN:
                start = block_cost[~time_restrictions].idxmin()
            else:
                start = block_cost[~time_restrictions].idxmax()

            start = start.event_value

            schedule.loc[
                start : start + sensor.event_resolution * (rows_to_fill - 1)
            ] = power

        else:
            raise ValueError(f"Unknown load type '{load_type}'")

        return schedule.tz_convert(self.start.tzinfo)

    def deserialize_flex_config(self):
        """ """
        if self.flex_model is None:
            self.flex_model = {}

        self.flex_model = ShiftableLoadFlexModelSchema(
            start=self.start, end=self.end, sensor=self.sensor
        ).load(self.flex_model)

        self.flex_context = FlexContextSchema().load(self.flex_context)
