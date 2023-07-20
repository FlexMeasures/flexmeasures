from __future__ import annotations

from math import ceil
from datetime import timedelta
import pytz

import pandas as pd

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
        """Schedule a load, defined as a `power` and a `duration`, within the specified time window.
        For example, this scheduler can plan the start of a process that lasts 5h and requires a power of 10kW.

        This scheduler supports three types of `load_types`:
            - Inflexible: this load requires to be scheduled as soon as possible.
            - Breakable: this load can be divisible in smaller consumption periods.
            - Shiftable: this load can start at any time within the specified time window.

        The resulting schedule provides the power flow at each time period.

        Parameters
        ==========

        cost_sensor: it defines the utility (economic, environmental, ) in each
                     time period. It has units of quantity/energy, for example, EUR/kWh.
        power: nominal power of the load.
        duration: time that the load lasts.

        optimization_sense: objective of the scheduler, to maximize or minimize.
        time_restrictions: time periods in which the load cannot be schedule to.
        load_type: Inflexible, Breakable or Shiftable.

        :returns:               The computed schedule.
        """

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

        # get cost data
        cost = cost_sensor.search_beliefs(
            event_starts_after=start,
            event_ends_before=end,
            resolution=resolution,
            one_deterministic_belief_per_event=True,
            beliefs_before=belief_time,
        )
        cost = simplify_index(cost)

        # create an empty schedule
        schedule = pd.Series(
            index=pd.date_range(
                start,
                end,
                freq=sensor.event_resolution,
                inclusive="left",
                name="event_start",
            ),
            data=0,
            name="event_value",
        )

        # optimize schedule for tomorrow. We can fill len(schedule) rows, at most
        rows_to_fill = min(ceil(duration / cost_sensor.event_resolution), len(schedule))

        # convert power to energy using the resolution of the sensor.
        # e.g. resolution=15min, power=1kW -> energy=250W
        energy = power * cost_sensor.event_resolution / timedelta(hours=1)

        if rows_to_fill > len(schedule):
            raise ValueError(
                f"Duration of the period exceeds the schedule window. The resulting schedule will be trimmed to fit the planning window ({start}, {end})."
            )

        # check if the time_restrictions allow for a load of the duration provided
        if load_type in [LoadType.INFLEXIBLE, LoadType.SHIFTABLE]:
            # get start time instants that are not feasible, i.e. some time during the ON period goes through
            # a time restriction interval
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

        # create schedule
        if load_type == LoadType.INFLEXIBLE:
            self.compute_inflexible(schedule, time_restrictions, rows_to_fill, energy)
        elif load_type == LoadType.BREAKABLE:
            self.compute_breakable(
                schedule,
                optimization_sense,
                time_restrictions,
                cost,
                rows_to_fill,
                energy,
            )
        elif load_type == LoadType.SHIFTABLE:
            self.compute_shiftable(
                schedule,
                optimization_sense,
                time_restrictions,
                cost,
                rows_to_fill,
                energy,
            )
        else:
            raise ValueError(f"Unknown load type '{load_type}'")

        return schedule.tz_convert(self.start.tzinfo)

    def compute_inflexible(
        self,
        schedule: pd.Series,
        time_restrictions: pd.Series,
        rows_to_fill: int,
        energy: float,
    ) -> None:
        """Schedule load as early as possible."""
        start = time_restrictions[~time_restrictions].index[0]

        schedule.loc[start : start + self.resolution * (rows_to_fill - 1)] = energy

    def compute_breakable(
        self,
        schedule: pd.Series,
        optimization_sense: OptimizationSense,
        time_restrictions: pd.Series,
        cost: pd.DataFrame,
        rows_to_fill: int,
        energy: float,
    ) -> None:
        """Break up schedule and divide it over the time slots with the largest utility (max/min cost depending on optimization_sense)."""
        cost = cost[~time_restrictions].reset_index()

        if optimization_sense == OptimizationSense.MIN:
            cost_ranking = cost.sort_values(
                by=["event_value", "event_start"], ascending=[True, True]
            )
        else:
            cost_ranking = cost.sort_values(
                by=["event_value", "event_start"], ascending=[False, True]
            )

        schedule.loc[cost_ranking.head(rows_to_fill).event_start] = energy

    def compute_shiftable(
        self,
        schedule: pd.Series,
        optimization_sense: OptimizationSense,
        time_restrictions: pd.Series,
        cost: pd.DataFrame,
        rows_to_fill: int,
        energy: float,
    ) -> None:
        """Schedules a block of consumption/production of `rows_to_fill` periods to maximize a utility."""
        block_cost = simplify_index(
            cost.rolling(rows_to_fill).sum().shift(-rows_to_fill + 1)
        )

        if optimization_sense == OptimizationSense.MIN:
            start = block_cost[~time_restrictions].idxmin()
        else:
            start = block_cost[~time_restrictions].idxmax()

        start = start.event_value

        schedule.loc[start : start + self.resolution * (rows_to_fill - 1)] = energy

    def deserialize_flex_config(self):
        """Deserialize flex_model using the schema ShiftableLoadFlexModelSchema and
        flex_context using FlexContextSchema
        """
        if self.flex_model is None:
            self.flex_model = {}

        self.flex_model = ShiftableLoadFlexModelSchema(
            start=self.start, end=self.end, sensor=self.sensor
        ).load(self.flex_model)

        self.flex_context = FlexContextSchema().load(self.flex_context)
