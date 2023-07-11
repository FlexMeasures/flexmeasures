from __future__ import annotations

from datetime import datetime, timedelta

import timely_beliefs as tb
import pandas as pd

from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.aggregation import AggregatorSchema

from flexmeasures.utils.time_utils import server_now


class AggregatorReporter(Reporter):
    """This reporter applies an aggregation function to multiple sensors"""

    __version__ = "1"
    __author__ = "Seita"
    schema = AggregatorSchema()
    weights: dict
    method: str

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

        if belief_time is None:
            belief_time = server_now()

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
        output_df = output_df.aggregate(self.method, axis=1)

        # convert BeliefsSeries into a BeliefsDataFrame
        output_df = output_df.to_frame("event_value")
        output_df["belief_time"] = belief_time
        output_df["cumulative_probability"] = 0.5
        output_df["source"] = self.data_source

        output_df = output_df.set_index(
            ["belief_time", "source", "cumulative_probability"], append=True
        )

        return output_df
