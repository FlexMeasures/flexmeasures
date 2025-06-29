from __future__ import annotations

import sys
from datetime import datetime

import pandas as pd
from darts import TimeSeries
from darts.dataprocessing.transformers import MissingValuesFiller
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.utils import get_data_source

from ..exception import CustomException
from ..logger import logging


class BasePipeline:
    def __init__(
        self,
        sensors: dict[str, int],
        regressors: list[str],
        target: str,
        n_hours_to_predict: int,
        max_forecast_horizon: int,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
    ) -> None:
        self.sensors = sensors
        self.regressors = regressors
        self.target = target
        self.n_hours_to_predict = n_hours_to_predict
        self.max_forecast_horizon = max_forecast_horizon
        self.event_starts_after = event_starts_after
        self.event_ends_before = event_ends_before

    def load_data(self) -> TimeSeries:
        """
        Load the data from dict of sensor id's.

        Example: sensors={'derived_demand':4612,'Ta':4613}.
        """
        try:
            logging.debug("Loading data from %s", self.sensors)
            sensor_dfs = []
            for name, sensor_id in self.sensors.items():

                sensor = db.session.get(Sensor, sensor_id)

                forecasting_source = [
                    get_data_source(
                        data_source_name="forecaster", data_source_type="forecaster"
                    ),
                ]  # Data source of forecasts

                data_sources = {
                    x
                    for x in sensor.search_data_sources()
                    if x not in forecasting_source
                }  # Get all data sources except forecaster which is data source of forecasts

                df = sensor.search_beliefs(
                    event_starts_after=self.event_starts_after,
                    event_ends_before=self.event_ends_before,
                    resolution=sensor.event_resolution,
                    source=data_sources,
                ).reset_index()

                df[["time", name]] = df[["event_start", "event_value"]].copy()
                df_filtered = df[["time", name]]

                # check if sensor data has missing data and fills it.
                df_filtered_darts = self.detect_and_fill_missing_values(
                    df=df_filtered,
                    sensor_name=name,
                    start=self.event_starts_after,
                    end=self.event_ends_before,
                )
                sensor_dfs.append(df_filtered_darts)

            if len(sensor_dfs) == 1:
                data_darts = sensor_dfs[0]
            else:
                data_darts = TimeSeries.concatenate(*sensor_dfs, axis=1)

            logging.debug("Data loaded successfully from %s", self.sensors)
            return data_darts
        except Exception as e:
            raise CustomException(f"Error loading data: {e}", sys)

    def split_data(self, df: TimeSeries) -> tuple:
        """
        Split the data into train and test sets.
        The test size is equal to self.n_hours_to_predict (168, i.e. 7 days by default).
        """
        try:
            logging.debug("Splitting data into train and test sets.")

            if (
                "auto_regressive" in self.regressors
                or "autoregressive" in self.regressors
            ):
                logging.info("Using autoregressive forecasting.")

                y = df[self.target]

                logging.debug("Data split successfully with autoregressive lags.")
                return ([], y)
            # Existing logic for using regressors
            X = df[self.regressors]
            y = df[self.target]

            logging.debug("Data split successfully.")
            return X, y
        except Exception as e:
            raise CustomException(f"Error splitting data: {e}", sys)

    def detect_and_fill_missing_values(
        self,
        df: pd.DataFrame,
        sensor_name: str,
        start: datetime,
        end: datetime,
        interpolate_kwargs: dict = None,
        fill: float = 0,
    ) -> TimeSeries:
        """
        Detects and fills missing values in a time series using the Darts `MissingValuesFiller` transformer.

        This method interpolates missing values in the time series using the `pd.DataFrame.interpolate()` method.

        Parameters:
        - df (pd.DataFrame): The input dataframe containing time series data with a "time" column.
        - sensor_name (str): The name of the sensor (used for logging).
        - start (datetime): The desired start time of the time series.
        - end (datetime): The desired end time of the time series.
        - interpolate_kwargs (dict, optional): Additional keyword arguments passed to `MissingValuesFiller`,
          which internally calls `pd.DataFrame.interpolate()`. For more details, see the
          `Darts documentation <https://unit8co.github.io/darts/generated_api/darts.utils.missing_values.html#darts.utils.missing_values.fill_missing_values>`_.
        - fill (float): value used to fill gaps in case there is no data at all.
        Returns:
        - TimeSeries: The time series with missing values filled.

        Raises:
        - ValueError: If the input dataframe is empty.
        - logging.warning: If missing values are detected and filled using `pd.DataFrame.interpolate()`.
        """

        if df.empty:
            transformer = MissingValuesFiller(fill=fill)
            logging.warning(
                f"Sensor '{self.sensors[sensor_name]}' has no data from {start} to {end}. Filling with {fill}."
            )
        else:
            transformer = MissingValuesFiller(fill="auto")

        data = df.copy()
        data["time"] = pd.to_datetime(data["time"], utc=True)
        sensor = db.session.get(Sensor, self.sensors[sensor_name])

        # Convert start & end to UTC
        start = pd.to_datetime(start).tz_convert("UTC")
        end = pd.to_datetime(end).tz_convert("UTC")
        # last event_start in sensor df is end - event_resolution
        last_event_start = end - pd.Timedelta(
            hours=sensor.event_resolution.total_seconds() / 3600
        )

        # Ensure the first and last event_starts match the expected dates specified in the CLI arguments
        # Add start time if missing
        if data["time"].iloc[0] != start:
            new_row_start = pd.DataFrame({"time": [start], "target": [None]})
            data = pd.concat([new_row_start, data], ignore_index=True)

        # Add end time if missing
        if data["time"].iloc[-1] != last_event_start:
            new_row_end = pd.DataFrame({"time": [last_event_start], "target": [None]})
            data = pd.concat([data, new_row_end], ignore_index=True)

        # Prepare data for Darts TimeSeries
        data["time"] = data["time"].dt.tz_localize(None)
        data_darts = TimeSeries.from_dataframe(
            df=data,
            time_col="time",
            fill_missing_dates=True,  # Ensures all timestamps are present, filling gaps with NaNs
            freq=sensor.event_resolution,
        )
        data_darts_gaps = data_darts.gaps()

        # Fill missing values using Darts transformer
        if not data_darts_gaps.empty:
            data_darts = transformer.transform(data_darts, **(interpolate_kwargs or {}))

            logging.warning(
                f"Sensor '{sensor_name}' has gaps:\n{data_darts_gaps.to_string()}\n"
                "These were filled using `pd.DataFrame.interpolate()` method."
            )

        return data_darts
