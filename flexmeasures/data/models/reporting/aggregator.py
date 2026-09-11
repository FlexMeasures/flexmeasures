from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pint
from flask import current_app

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.reporting.aggregation import (
    AggregatorConfigSchema,
    AggregatorParametersSchema,
)

from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.unit_utils import convert_units, units_are_convertible


def units_match(unit: str, units: list[str]) -> bool:
    """Tell whether a sensor unit is one of the units to filter on.

    A unit matches when it is spelled exactly like one of them, or when it measures the same quantity,
    so that filtering on "MW" also finds sensors recording in "kW", but not sensors recording in "MWh".
    """
    for other_unit in units:
        if unit == other_unit:
            return True
        if units_are_convertible(unit, other_unit, duration_known=False):
            return True
    return False


class AggregatorReporter(Reporter):
    """This reporter applies an aggregation function to multiple sensors.

    The sensors to aggregate can be listed one by one, as `input` parameters, but they can also be selected in the reporter's configuration,
    which is what makes this reporter useful for a whole site: name an asset and every sensor below it is aggregated,
    optionally narrowed down by a pattern on the sensor name and by the units the sensors record in.

    Values are converted to the unit of the output sensor, and resampled to its resolution,
    so that sensors recording in different units and at different resolutions can be aggregated.
    """

    __version__ = "2"
    __author__ = "Seita"

    _config_schema = AggregatorConfigSchema()
    _parameters_schema = AggregatorParametersSchema()

    weights: dict
    method: str

    @property
    def input_sensors(self) -> list:
        """Return the sensors read by this reporter, including the ones selected in its config."""
        return self._resolve_sensors(super().input_sensors, self._find_sensors())

    def _find_sensors(self) -> list[Sensor]:
        """Find the sensors that the reporter's configuration selects.

        The pool of candidates holds the sensors of the asset named in the `asset` field and of its offspring, together with the sensors listed in the `sensors` field.
        The `sensor_name_pattern` and `sensor_units` fields then narrow that pool down.
        Sensors are returned ordered by ID, so that an aggregation over a site does not depend on the order in which its sensors happen to be loaded.
        """
        asset: GenericAsset | None = self._config.get("asset")
        listed_sensors: list[Sensor] = self._config.get("sensors") or []
        name_pattern: str | None = self._config.get("sensor_name_pattern")
        units: list[str] | None = self._config.get("sensor_units")

        candidates: dict[int, Sensor] = {}
        if asset is not None:
            for sub_asset in [asset] + asset.offspring:
                for sensor in sub_asset.sensors:
                    candidates[sensor.id] = sensor
        for sensor in listed_sensors:
            candidates[sensor.id] = sensor

        sensors = list(candidates.values())

        if name_pattern is not None:
            pattern = re.compile(name_pattern)
            sensors = [sensor for sensor in sensors if pattern.search(sensor.name)]

        if units:
            sensors = [sensor for sensor in sensors if units_match(sensor.unit, units)]

        return sorted(sensors, key=lambda sensor: sensor.id)

    def _collect_input_descriptions(
        self, input: list[dict[str, Any]], output_sensor: Sensor
    ) -> list[dict[str, Any]]:
        """List what to read, combining the `input` parameters with the sensors selected in the config.

        The input descriptions are copied, so that reading them does not consume the parameters the reporter was given.
        A selected sensor that is already described as an input is left to that description, which is the more specific of the two.
        The output sensor is never aggregated into itself, which it otherwise would be when it sits below the configured asset.
        """
        input_descriptions = [dict(input_description) for input_description in input]
        described_sensor_ids = {
            input_description["sensor"].id for input_description in input_descriptions
        }

        for sensor in self._find_sensors():
            if sensor.id in described_sensor_ids or sensor.id == output_sensor.id:
                continue
            input_descriptions.append({"sensor": sensor})

        return input_descriptions

    def _convert_to_output_unit(
        self,
        df: pd.DataFrame,
        sensor: Sensor,
        output_sensor: Sensor,
        resolution: timedelta,
    ) -> pd.DataFrame:
        """Convert the values read from one input sensor to the unit of the output sensor.

        A sensor without a unit is left alone, with a warning, because an empty unit says nothing about what its values mean.
        """
        if sensor.unit == output_sensor.unit:
            return df

        if sensor.unit == "" or output_sensor.unit == "":
            current_app.logger.warning(
                f"Not converting the values of sensor {sensor.id} ({sensor.name}) from '{sensor.unit}' to '{output_sensor.unit}', because one of these units is empty."
                f" Set a unit on both sensors, or set the reporter's `convert_units` config field to False to aggregate raw values on purpose."
            )
            return df

        try:
            df["event_value"] = convert_units(
                df["event_value"],
                from_unit=sensor.unit,
                to_unit=output_sensor.unit,
                event_resolution=resolution,
            )
        except (pint.errors.PintError, ValueError) as e:
            raise ValueError(
                f"Cannot aggregate sensor {sensor.id} ({sensor.name}), which records in '{sensor.unit}', onto sensor {output_sensor.id} ({output_sensor.name}), which records in '{output_sensor.unit}': {e}"
                f" Either aggregate sensors that record a comparable quantity, or set the reporter's `convert_units` config field to False to aggregate raw values."
            )

        return df

    def _compute_report(
        self,
        start: datetime,
        end: datetime,
        output: list[dict[str, Any]],
        input: list[dict[str, Any]] | None = None,
        resolution: timedelta | None = None,
        belief_time: datetime | None = None,
        belief_horizon: timedelta | None = None,
    ) -> list[dict[str, Any]]:
        """
        This method merges all the BeliefDataFrames into a single one, dropping
        all indexes but event_start, and applies an aggregation function over the
        columns.
        """

        method: str = self._config.get("method", "sum")
        weights: dict = self._config.get("weights", {})
        convert_to_output_unit: bool = self._config.get("convert_units", True)

        output_sensor: Sensor = output[0]["sensor"]

        # Read and resample to the resolution of the output sensor, unless the caller asked for another resolution.
        if resolution is None:
            resolution = output_sensor.event_resolution

        input_descriptions = self._collect_input_descriptions(
            input or [], output_sensor=output_sensor
        )
        if len(input_descriptions) == 0:
            raise ValueError(
                "The AggregatorReporter has no sensors to aggregate."
                " Name them in the `input` parameters, or select them in the reporter's config with the `asset`, `sensors`, `sensor_name_pattern` and `sensor_units` fields."
            )

        dataframes = []

        if belief_time is None and belief_horizon is None:
            belief_time = server_now()

        for input_description in input_descriptions:
            sensor: Sensor = input_description.pop("sensor")
            # if name is not in belief_search_config, using the Sensor id instead
            column_name = input_description.pop("name", f"sensor_{sensor.id}")

            source = input_description.pop(
                "source", input_description.pop("sources", None)
            )
            if source is not None and not isinstance(source, list):
                source = [source]

            df = sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                resolution=resolution,
                beliefs_before=belief_time,
                horizons_at_most=belief_horizon,
                source=source,
                one_deterministic_belief_per_event=True,
                **input_description,
            )

            # Check for multi-sourced events (i.e. multiple sources for a single event)
            if len(df.lineage.events) != len(df):
                duplicate_events = df[
                    df.index.get_level_values("event_start").duplicated()
                ]
                raise ValueError(
                    f"{len(duplicate_events)} event(s) are duplicate. First duplicate: {duplicate_events[0]}. Consider using (more) source filters."
                )

            # Check for multiple sources within the entire frame (excluding different versions of the same source)
            # Raise error if that is the case and no source filter was applied - user should be explicit here
            unique_sources = df.lineage.sources
            properties = [
                "name",
                "type",
                "model",
            ]  # properties to identify different versions of the same source
            if (
                len(unique_sources) > 1
                and not all(
                    getattr(source, prop) == getattr(unique_sources[0], prop)
                    for prop in properties
                    for source in unique_sources
                )
                and (source is None or len(source) == 0)
            ):
                raise ValueError(
                    f"Missing attribute 'sources' for input sensor {sensor.id}: {sensor.name} (to identify one specific source). The field  `sources` is required when having data with multiple sources within the time window, to ensure only required data is used in the reporter. "
                    f"We found data from the following sources: {[source.id for source in unique_sources]}."
                )

            # drop all indexes but event_start
            df = df.droplevel([1, 2, 3])

            # express the values in the unit of the output sensor
            if convert_to_output_unit and not df.empty:
                df = self._convert_to_output_unit(
                    df, sensor, output_sensor, resolution=resolution
                )

            # apply weight
            if column_name in weights:
                df *= weights[column_name]

            dataframes.append(df)

        output_df = pd.concat(dataframes, axis=1)

        # apply aggregation method
        output_df = output_df.aggregate(method, axis=1)

        # convert BeliefsSeries into a BeliefsDataFrame
        output_df = output_df.to_frame("event_value")
        if belief_time is not None:
            belief_col = "belief_time"
            output_df[belief_col] = belief_time
        elif belief_horizon is not None:
            belief_col = "belief_horizon"
            output_df[belief_col] = belief_horizon
        output_df["cumulative_probability"] = 0.5
        output_df["source"] = self.data_source
        output_df.sensor = output_sensor
        output_df.event_resolution = output_sensor.event_resolution

        output_df = output_df.set_index(
            [belief_col, "source", "cumulative_probability"], append=True
        )

        return [
            {
                "name": "aggregate",
                "column": "event_value",
                "sensor": output_sensor,
                "data": output_df,
            }
        ]
