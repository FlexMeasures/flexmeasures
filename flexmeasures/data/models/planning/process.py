from __future__ import annotations

from math import ceil
from datetime import timedelta
import pytz

import pandas as pd

from flexmeasures.data.models.planning import Scheduler

from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.scheduling.process import (
    ProcessSchedulerFlexModelSchema,
    ProcessType,
    OptimizationDirection,
)
from flexmeasures.data.schemas.scheduling import FlexContextSchema


class ProcessScheduler(Scheduler):

    __version__ = "1"
    __author__ = "Seita"

    def compute(self) -> pd.Series | None:
        """Schedule a process, defined as a `power` and a `duration`, within the specified time window.
        To schedule a battery, please, refer to the StorageScheduler.

        For example, this scheduler can plan the start of a process of type `SHIFTABLE` that lasts 5h and requires a power of 10kW.
        In that case, the scheduler will find the best (as to minimize/maximize the cost) hour to start the process.

        This scheduler supports three types of `process_types`:
            - INFLEXIBLE: this process needs to be scheduled as soon as possible.
            - BREAKABLE: this process can be broken up into smaller segments with some idle time in between.
            - SHIFTABLE: this process can start at any time within the specified time window.

        The resulting schedule provides the power flow at each time period.

        Parameters
        ==========

        consumption_price_sensor: it defines the utility (economic, environmental, ) in each
                     time period. It has units of quantity/energy, for example, EUR/kWh.
        power: nominal power of the process.
        duration: time that the process last.

        optimization_direction: objective of the scheduler, to maximize or minimize.
        time_restrictions: time periods in which the process cannot be schedule to.
        process_type: INFLEXIBLE, BREAKABLE or SHIFTABLE.

        :returns:               The computed schedule.
        """

        if not self.config_deserialized:
            self.deserialize_config()

        start = self.start.astimezone(pytz.utc)
        end = self.end.astimezone(pytz.utc)
        resolution = self.resolution
        belief_time = self.belief_time
        sensor = self.sensor

        consumption_price_sensor: Sensor = self.flex_context.get(
            "consumption_price_sensor"
        )
        duration: timedelta = self.flex_model.get("duration")
        power = self.flex_model.get("power")
        optimization_direction = self.flex_model.get("optimization_direction")
        process_type: ProcessType = self.flex_model.get("process_type")
        time_restrictions = self.flex_model.get("time_restrictions")

        # get cost data
        cost = consumption_price_sensor.search_beliefs(
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

        # we can fill duration/resolution rows or, if the duration is larger than the schedule
        # window, fill the entire window.
        rows_to_fill = min(ceil(duration / self.resolution), len(schedule))

        # duration of the process exceeds the scheduling window
        if rows_to_fill == len(schedule):
            if time_restrictions.sum() > 0:
                raise ValueError(
                    "Cannot handle time restrictions if the duration of the process exceeds that of the schedule window."
                )

            schedule[:] = power

            if self.return_multiple:
                return [
                    {
                        "name": "process_schedule",
                        "sensor": sensor,
                        "data": schedule,
                    }
                ]
            else:
                return schedule

        if process_type in [ProcessType.INFLEXIBLE, ProcessType.SHIFTABLE]:
            start_time_restrictions = (
                self.block_invalid_starting_times_for_whole_process_scheduling(
                    process_type, time_restrictions, duration, rows_to_fill
                )
            )
        else:  # ProcessType.BREAKABLE
            if (~time_restrictions).sum() < rows_to_fill:
                raise ValueError(
                    "Cannot allocate a block of time {duration} given the time restrictions provided."
                )

        # create schedule
        if process_type == ProcessType.INFLEXIBLE:
            self.compute_inflexible(
                schedule, start_time_restrictions, rows_to_fill, power
            )
        elif process_type == ProcessType.BREAKABLE:
            self.compute_breakable(
                schedule,
                optimization_direction,
                time_restrictions,
                cost,
                rows_to_fill,
                power,
            )
        elif process_type == ProcessType.SHIFTABLE:
            self.compute_shiftable(
                schedule,
                optimization_direction,
                start_time_restrictions,
                cost,
                rows_to_fill,
                power,
            )
        else:
            raise ValueError(f"Unknown process type '{process_type}'")

        if self.return_multiple:
            return [
                {
                    "name": "process_schedule",
                    "sensor": sensor,
                    "data": schedule.tz_convert(self.start.tzinfo),
                }
            ]
        else:
            return schedule.tz_convert(self.start.tzinfo)

    def block_invalid_starting_times_for_whole_process_scheduling(
        self,
        process_type: ProcessType,
        time_restrictions: pd.Series,
        duration: timedelta,
        rows_to_fill: int,
    ) -> pd.Series:
        """Blocks time periods where the process cannot be schedule into, making
          sure no other time restrictions runs in the middle of the activation of the process

        More technically, this function applying an erosion of the time_restrictions array with a block of length duration.

        Then, the condition if time_restrictions.sum() == len(time_restrictions):, makes sure that at least we have a spot to place the process.

        For example:

            time_restriction = [1 0 0 1 1 1 0 0 1 0]

            # applying a dilation with duration = 2
            time_restriction = [1 0 1 1 1 1 0 1 1 1]

        We can only fit a block of duration = 2 in the positions 1 and 6. sum(start_time_restrictions) == 8,
        while the len(time_restriction) == 10, which means we have 10-8=2 positions.

        :param process_type: INFLEXIBLE, SHIFTABLE or BREAKABLE
        :param time_restrictions: boolean time series indicating time periods in which the process cannot be scheduled.
        :param duration: (datetime) duration of the length
        :param rows_to_fill: (int) time periods that the process lasts
        :return: filtered time restrictions
        """

        # get start time instants that are not feasible, i.e. some time during the ON period goes through
        # a time restriction interval
        start_time_restrictions = (
            time_restrictions.rolling(duration).max().shift(-rows_to_fill + 1)
        )
        start_time_restrictions = (
            start_time_restrictions == 1
        ) | start_time_restrictions.isna()

        if (~start_time_restrictions).sum() == 0:
            raise ValueError(
                "Cannot allocate a block of time {duration} given the time restrictions provided."
            )

        return start_time_restrictions

    def compute_inflexible(
        self,
        schedule: pd.Series,
        time_restrictions: pd.Series,
        rows_to_fill: int,
        power: float,
    ) -> None:
        """Schedule process as early as possible."""
        start = time_restrictions[~time_restrictions].index[0]

        schedule.loc[start : start + self.resolution * (rows_to_fill - 1)] = power

    def compute_breakable(
        self,
        schedule: pd.Series,
        optimization_direction: OptimizationDirection,
        time_restrictions: pd.Series,
        cost: pd.DataFrame,
        rows_to_fill: int,
        power: float,
    ) -> None:
        """Break up schedule and divide it over the time slots with the largest utility (max/min cost depending on optimization_direction)."""
        cost = cost[~time_restrictions].reset_index()

        if optimization_direction == OptimizationDirection.MIN:
            cost_ranking = cost.sort_values(
                by=["event_value", "event_start"], ascending=[True, True]
            )
        else:
            cost_ranking = cost.sort_values(
                by=["event_value", "event_start"], ascending=[False, True]
            )

        schedule.loc[cost_ranking.head(rows_to_fill).event_start] = power

    def compute_shiftable(
        self,
        schedule: pd.Series,
        optimization_direction: OptimizationDirection,
        time_restrictions: pd.Series,
        cost: pd.DataFrame,
        rows_to_fill: int,
        power: float,
    ) -> None:
        """Schedules a block of consumption/production of `rows_to_fill` periods to maximize a utility."""
        block_cost = simplify_index(
            cost.rolling(rows_to_fill).sum().shift(-rows_to_fill + 1)
        )

        if optimization_direction == OptimizationDirection.MIN:
            start = block_cost[~time_restrictions].idxmin()
        else:
            start = block_cost[~time_restrictions].idxmax()

        start = start.iloc[0]

        schedule.loc[start : start + self.resolution * (rows_to_fill - 1)] = power

    def deserialize_flex_config(self):
        """Deserialize flex_model using the schema ProcessSchedulerFlexModelSchema and
        flex_context using FlexContextSchema
        """
        if self.flex_model is None:
            self.flex_model = {}

        self.flex_model = ProcessSchedulerFlexModelSchema(
            start=self.start, end=self.end, sensor=self.sensor
        ).load(self.flex_model)

        self.flex_context = FlexContextSchema().load(self.flex_context)
