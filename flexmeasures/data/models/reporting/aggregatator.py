from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta

import timely_beliefs as tb
import pandas as pd

from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.aggregation import (
    AggregatorSchema,
    AggregationMethod,
)
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.utils.time_utils import server_now


class AggregatorReporter(Reporter):
    """This reporter applies an aggregation function to multiple sensors"""

    __version__ = "1"
    __author__ = None
    schema = AggregatorSchema()
    transformations: list[dict[str, Any]] = None
    final_df_output: str = None

    def deserialize_config(self):
        # call Reporter deserialize_config
        super().deserialize_config()

        # extract AggregatorReporter specific fields
        self.method = self.reporter_config.get("method")
        self.weights = self.reporter_config.get("weights", dict())

    def _compute(
        self,
        start: datetime,
        end: datetime,
        input_resolution: timedelta | None = None,
        belief_time: datetime | None = None,
    ) -> tb.BeliefsDataFrame:
        """
        This method merges all the BeliefDataFrames into a single one, dropping
        all indexes but event_start, and applies an aggregation function over the
        columns.
        """

        dataframes = []

        for belief_search_config in self.beliefs_search_configs:
            # if alias is not in belief_search_config, using the Sensor id instead
            column_name = belief_search_config.get(
                "alias", f"sensor_{belief_search_config['sensor'].id}"
            )
            data = self.data[column_name].droplevel([1, 2, 3])

            # apply weight
            if column_name in self.weights:
                data *= self.weights[column_name]

            dataframes.append(data)

        output_df = pd.concat(dataframes, axis=1)

        # apply aggregation method
        if self.method == AggregationMethod.SUM:
            output_df = output_df.sum(axis=1)
        elif self.method == AggregationMethod.MEAN:
            output_df = output_df.mean(axis=1)

        # convert BeliefSeries to BeliefDataFrame
        timed_beliefs = [
            TimedBelief(
                sensor=output_df.sensor,
                source=self.data_source,
                belief_time=server_now(),
                event_start=event_start,
                event_value=event_value,
            )
            for event_start, event_value in output_df.items()
        ]

        return tb.BeliefsDataFrame(timed_beliefs)
