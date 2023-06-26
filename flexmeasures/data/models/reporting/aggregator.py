from __future__ import annotations

from datetime import datetime, timedelta

import timely_beliefs as tb
import pandas as pd

from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.aggregation import AggregatorConfigSchema

from flexmeasures.utils.time_utils import server_now


class AggregatorReporter(Reporter):
    """This reporter applies an aggregation function to multiple sensors"""

    __version__ = "1"
    __author__ = "Seita"

    _config_schema = AggregatorConfigSchema()

    weights: dict
    method: str

    def _compute_report(
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

        method: str = self._config.get("method")
        weights: list = self._config.get("weights", {})
        data: list = self._config.get("data")

        dataframes = []

        for d in data:
            # if alias is not in belief_search_config, using the Sensor id instead
            column_name = d.get("alias", f"sensor_{d['sensor'].id}")

            df = (
                d["sensor"]
                .search_beliefs(
                    event_starts_after=start,
                    event_ends_before=end,
                    resolution=input_resolution,
                    beliefs_before=belief_time,
                )
                .droplevel([1, 2, 3])
            )

            # apply weight
            if column_name in weights:
                df *= weights[column_name]

            dataframes.append(df)

        output_df = pd.concat(dataframes, axis=1)

        if belief_time is None:
            belief_time = server_now()

        # apply aggregation method
        output_df = output_df.aggregate(method, axis=1)

        # convert BeliefsSeries into a BeliefsDataFrame
        output_df = output_df.to_frame("event_value")
        output_df["belief_time"] = belief_time
        output_df["cumulative_probability"] = 0.5
        output_df["source"] = self.data_source

        output_df = output_df.set_index(
            ["belief_time", "source", "cumulative_probability"], append=True
        )

        return output_df
