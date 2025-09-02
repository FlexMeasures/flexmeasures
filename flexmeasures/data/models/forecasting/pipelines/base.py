from __future__ import annotations

import sys
import logging
from datetime import datetime
from functools import reduce

import pandas as pd
from darts import TimeSeries
from darts.dataprocessing.transformers import MissingValuesFiller
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor
from timely_beliefs import utils as tb_utils

from flexmeasures.data.models.forecasting.exceptions import CustomException


class BasePipeline:
    """
    Base class for Train and Predict pipelines.

    This class handles loading and preprocessing time series data for training or
    prediction, including missing value handling and splitting into regressors (X)
    and target (y).

    ## Covariate semantics
    Data for `past_covariates` and `future_covariates` is loaded broadly enough to cover:
    - from the beginning of the training/predict period,
    - through the end of the predict period,
    - plus `max_forecast_horizon` (needed for the last forecast step).

    Later, `split_data_all_beliefs` and `_generate_splits` slice this superset into
    per-horizon inputs:

    - **Past covariates**: realized (historical) data aligned up to each split's `target_end`
      (just before the predicted step), selecting the most recent belief per event_start.
    - **Future covariates**: realized data up to `target_end` plus forecasts up to
      `target_end + max_forecast_horizon`, selecting the most recent belief per event_start.
    - **Target series**: realized target values from `target_start` through `target_end`
      (the conditioning context for forecasting).

    Parameters
    ----------
    sensors : dict[str, int]
        Mapping of sensor names to sensor IDs.
    past_regressors : list[str] | None
        Sensor names used only as historical (past) covariates.
    future_regressors : list[str]
        Sensor names used as future covariates (with forecast data).
    target : str
        Name of the target sensor (key in `sensors`).
    n_steps_to_predict : int
        Number of forecast iterations (steps at target resolution).
    max_forecast_horizon : int
        Maximum look-ahead horizon, in steps of the target resolution.
    event_starts_after / event_ends_before : datetime | None
        Time boundaries for loading sensor events.
    """

    def __init__(
        self,
        sensors: dict[str, int],
        future_regressors: list[str],
        target: str,
        n_steps_to_predict: int,
        max_forecast_horizon: int,
        forecast_frequency: int,
        past_regressors: list[str] | None = None,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        predict_start: datetime | None = None,
        predict_end: datetime | None = None,
    ) -> None:
        self.sensors = sensors
        self.past_regressors = past_regressors
        self.future_regressors = future_regressors
        self.target = target
        self.n_steps_to_predict = n_steps_to_predict
        self.max_forecast_horizon = max_forecast_horizon
        self.horizons = range(
            (self.n_steps_to_predict + forecast_frequency - 1)
            // forecast_frequency
        )  # rounds up so we get the number of forecast steps of size `forecast_frequency` within `n_steps_to_predict`
        self.event_starts_after = event_starts_after
        self.event_ends_before = event_ends_before
        self.target_sensor = db.session.get(Sensor, self.sensors[self.target])
        self.predict_start = predict_start if predict_start else None
        self.predict_end = predict_end if predict_end else None
        self.max_forecast_horizon_in_hours = (
            self.max_forecast_horizon
            * self.target_sensor.event_resolution.total_seconds()
            / 3600
        )  # convert max_forecast_horizon to hours
        self.forecast_frequency = forecast_frequency

    def load_data_all_beliefs(self) -> pd.DataFrame:
        """
        This function fetches data for each sensor.
        If a sensor is listed as a future regressor, it fetches all available beliefs (including forecasts).

        Returns:
        - pd.DataFrame: A DataFrame containing all the data from each sensor.
        """
        try:
            logging.debug("Loading all data from %s", self.sensors)

            sensor_dfs = []
            for name, sensor_id in self.sensors.items():

                logging.debug(f"Loading data for {name} (sensor ID {sensor_id})")

                sensor = db.session.get(Sensor, sensor_id)
                sensor_event_ends_before = self.event_ends_before
                sensor_event_starts_after = self.event_starts_after

                most_recent_beliefs_only = True
                # Extend time range for future regressors
                if name in self.future_regressors:
                    sensor_event_ends_before = self.event_ends_before + pd.Timedelta(
                        hours=self.max_forecast_horizon_in_hours
                    )

                    most_recent_beliefs_only = False  # load all beliefs available to include forecasts available at each timestamp

                df = sensor.search_beliefs(
                    event_starts_after=sensor_event_starts_after,
                    event_ends_before=sensor_event_ends_before,
                    most_recent_beliefs_only=most_recent_beliefs_only,
                    exclude_source_types=(
                        ["forecaster"] if name in self.target else []
                    ),  # we exclude forecasters for target dataframe as to not use forecasts in target.
                )
                try:
                    # We resample regressors to the target sensor’s resolution so they align in time.
                    # This ensures the resulting DataFrame can be used directly for predictions.
                    df = tb_utils.replace_multi_index_level(
                        df,
                        "event_start",
                        df.event_starts.floor(self.target_sensor.event_resolution),
                    )
                except Exception as e:
                    logging.warning(f"Error during custom resample for {name}: {e}")

                df = df.reset_index()
                df[["event_start", "belief_time", "source", name]] = df[
                    ["event_start", "belief_time", "source", "event_value"]
                ].copy()
                df_filtered = df[["event_start", "belief_time", "source", name]]

                sensor_dfs.append(df_filtered)

            if len(sensor_dfs) == 1:
                data_pd = sensor_dfs[0]
            else:
                # When using future_covariate, the last day in its sensor_df extends beyond
                # the target and past regressors by "max_forecast_horizon."
                # To ensure we retain these additional future regressor records,
                # we use an outer join to merge all sensor_dfs DataFrames on the "event_start" and "belief_time" columns.

                data_pd = reduce(
                    lambda left, right: pd.merge(
                        left, right, on=["event_start", "belief_time"], how="outer"
                    ),
                    sensor_dfs,
                )
                data_pd = data_pd.sort_values(
                    by=["event_start", "belief_time"]
                ).reset_index(drop=True)
            data_pd["event_start"] = pd.to_datetime(
                data_pd["event_start"], utc=True
            ).dt.tz_localize(None)
            data_pd["belief_time"] = pd.to_datetime(
                data_pd["belief_time"], utc=True
            ).dt.tz_localize(None)

            return data_pd

        except Exception as e:
            raise CustomException(f"Error loading dataframe with all beliefs: {e}", sys)

    def split_data_all_beliefs(
        self, df: pd.DataFrame, is_predict_pipeline: bool = False
    ) -> tuple[
        list[TimeSeries] | None,
        list[TimeSeries] | None,
        list[TimeSeries],
        list[pd.Timestamp],
    ]:
        """
        Split the loaded sensor DataFrame into past covariates, future covariates,
        and target series across one or more simulated forecast times ("belief times").

        This is the main entry point for preparing model inputs. It:
        - Handles the autoregressive case (no regressors).
        - Or delegates to `_generate_splits`, which applies the sliding-window
        logic to produce per-belief covariate/target slices.

        Parameters
        ----------
        df : pd.DataFrame
            The full sensor data (from `load_data_all_beliefs`), with columns
            [event_start, belief_time, ...].
        is_predict_pipeline : bool, default False
            If True, generate splits for all prediction steps in `n_steps_to_predict`.
            If False, only generate one split (used in training).

        Returns
        -------
        past_covariates_list : list[TimeSeries] | None
            Past regressors up to each belief_time, or None if not used.
        future_covariates_list : list[TimeSeries] | None
            Future regressors (realized + forecasted) up to each forecast_end, or None if not used.
        target_list : list[TimeSeries]
            Target series truncated at each belief_time.
        belief_timestamps_list : list[pd.Timestamp]
            The simulated "now" timestamps when forecasts are issued, used to as the forecasts belief_time when saving to db.

        Notes
        -----
        The detailed semantics of how past/future covariates and targets
        are constructed for each split are documented in `_generate_splits`.
        """
        try:
            logging.debug("Splitting data target and covariates.")

            def _generate_splits(
                X_past_regressors_df: pd.DataFrame | None,
                X_future_regressors_df: pd.DataFrame | None,
                y: pd.DataFrame,
            ):
                """
                Generate past covariates, future covariates, and target series
                for multiple simulated prediction times ("belief times").

                For each simulated belief_time:
                - Past covariates contain realized regressor data up to `target_end`
                (just before the predictions start).
                - Future covariates include realized data up to `target_end`
                and forecasts extending up to `forecast_end` (`target_end + max_forecast_horizon`).
                - Target series (y) contain realized target values up to `target_end`
                (the last event_start available for making forecasts).
                - belief_time is the timestamp representing "when the forecast
                would have been made." It coincides with the belief_time
                of `target_end` — i.e., the last belief_time seen.

                This function loops through `n_steps_to_predict` (if this class is used by the predict pipeline),
                creating a sliding window of inputs for each prediction step.

                Parameters
                ----------
                X_past_regressors_df : pd.DataFrame | None
                    Past regressors (realized values before belief_time). None if not used.
                X_future_regressors_df : pd.DataFrame | None
                    Future regressors (realized + forecasted values). None if not used.
                y : pd.DataFrame
                    Target values, indexed by event_start and belief_time.

                Returns
                -------
                past_covariates_list : list[TimeSeries] | None
                future_covariates_list : list[TimeSeries] | None
                target_list : list[TimeSeries]
                belief_timestamps_list : list[pd.Timestamp]
                """

                target_sensor_resolution = self.target_sensor.event_resolution

                # target_start is the timestamp of the event_start of the first event in realizations
                target_start = pd.to_datetime(
                    self.event_starts_after, utc=True
                ).tz_localize(None)

                # target_end is the timestamp of the last event_start of realized data
                # belief_time in this module is the belief_time of the last realization to be used for forecasting at each prediction step.
                if self.predict_start:
                    first_target_end = pd.to_datetime(
                        self.predict_start - self.target_sensor.event_resolution,
                        utc=True,
                    ).tz_localize(None)
                    first_belief_time = pd.to_datetime(
                        self.predict_start, utc=True
                    ).tz_localize(None)
                else:
                    first_target_end = pd.to_datetime(
                        self.event_ends_before - self.target_sensor.event_resolution,
                        utc=True,
                    ).tz_localize(None)
                    first_belief_time = pd.to_datetime(
                        self.event_ends_before, utc=True
                    ).tz_localize(None)

                # The forecast window ends at target_end + max_forecast_horizon (+ 1 resolution).
                first_forecast_end = (
                    first_target_end
                    + pd.Timedelta(hours=self.max_forecast_horizon_in_hours)
                    + self.target_sensor.event_resolution
                )
                # Ensure the forecast_end is in UTC and has no timezone info
                first_forecast_end = pd.to_datetime(
                    first_forecast_end, utc=True
                ).tz_localize(None)

                target_list = []
                past_covariates_list = []
                future_covariates_list = []

                # Number of prediction iterations: all steps if predict pipeline, else just 1 (training)
                end_for_loop = self.n_steps_to_predict if is_predict_pipeline else 1
                belief_timestamps_list = []

                # Loop through each simulated forecast step and increase the belief_time and target_end by 1 target sensor resolution
                for index_offset in range(0, end_for_loop):

                    # Move belief_time and target_end forward one resolution per step
                    belief_time = first_belief_time + pd.Timedelta(
                        minutes=index_offset
                        * target_sensor_resolution.total_seconds()
                        / 60
                    )  # The timestamp to simulate the start of prediction, used to obtain future and past data relative to this timestamp.
                    target_end = first_target_end + pd.Timedelta(
                        minutes=index_offset
                        * target_sensor_resolution.total_seconds()
                        / 60
                    )

                    forecast_end = first_forecast_end + pd.Timedelta(
                        minutes=index_offset
                        * target_sensor_resolution.total_seconds()
                        / 60
                    )

                    # Split covariates and target series for this simulated forecast
                    past_covariates, future_covariates, y_split = (
                        self._split_covariates_data(
                            X_past_regressors_df=X_past_regressors_df,
                            X_future_regressors_df=X_future_regressors_df,
                            target_dataframe=y,
                            belief_time=belief_time,
                            target_start=target_start,
                            target_end=target_end,
                            forecast_end=forecast_end,
                        )
                    )

                    target_list.append(y_split)
                    past_covariates_list.append(past_covariates)
                    future_covariates_list.append(future_covariates)
                    belief_timestamps_list.append(belief_time)

                future_covariates_list = (
                    future_covariates_list
                    if future_covariates_list[0] is not None
                    else None
                )
                past_covariates_list = (
                    past_covariates_list
                    if past_covariates_list[0] is not None
                    else None
                )

                return (
                    past_covariates_list,
                    future_covariates_list,
                    target_list,
                    belief_timestamps_list,
                )

            if not self.past_regressors and not self.future_regressors:
                logging.info("Using autoregressive forecasting.")

                y = df[["event_start", "belief_time", self.target]].copy()

                _, _, target_list, belief_timestamps_list = _generate_splits(
                    None, None, y
                )

                logging.debug("Data split successfully with autoregressive lags.")
                return None, None, target_list, belief_timestamps_list
            # Existing logic for using regressors

            X_past_regressors_df = (
                df[
                    ["event_start", "source_y", "belief_time"]
                    + [r for r in self.past_regressors]
                ]
                if self.past_regressors
                else None
            )
            X_future_regressors_df = (
                df[["event_start", "source_y", "belief_time"] + self.future_regressors]
                if self.future_regressors != []
                else None
            )
            y = (
                df[["event_start", "belief_time", self.target]]
                .dropna()
                .reset_index(drop=True)
                .copy()
            )

            (
                past_covariates_list,
                future_covariates_list,
                target_list,
                belief_timestamps_list,
            ) = _generate_splits(X_past_regressors_df, X_future_regressors_df, y)

            return (
                past_covariates_list,
                future_covariates_list,
                target_list,
                belief_timestamps_list,
            )

        except Exception as e:
            raise CustomException(f"Error splitting data: {e}", sys)

    def detect_and_fill_missing_values(
        self,
        df: pd.DataFrame,
        sensor_names: str | list[str],
        start: datetime,
        end: datetime,
        interpolate_kwargs: dict = None,
        fill: float = 0.0,
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
        dfs = []
        if isinstance(sensor_names, str):
            sensor_names = [sensor_names]

        for sensor_name in sensor_names:
            if df.empty:
                sensor = db.session.get(Sensor, self.sensors[sensor_name])

                last_event_start = end - pd.Timedelta(
                    hours=sensor.event_resolution.total_seconds() / 3600
                )
                new_row_start = pd.DataFrame(
                    {"event_start": [start], f"{sensor_name}": [None]}
                )
                new_row_end = pd.DataFrame(
                    {"event_start": [last_event_start], f"{sensor_name}": [None]}
                )
                df = pd.concat([new_row_start, df, new_row_end], ignore_index=True)

                logging.debug(
                    f"Sensor '{self.sensors[sensor_name]}' has no data from {start} to {end}. Filling with {fill}."
                )
                transformer = MissingValuesFiller(fill=float(fill))
            else:
                transformer = MissingValuesFiller(fill="auto")

            data = df.copy()

            sensor = db.session.get(Sensor, self.sensors[sensor_name])

            # Convert start & end to UTC
            start = start.tz_localize(None)
            end = end.tz_localize(None)
            # last event_start in sensor df is end - event_resolution
            last_event_start = end

            # Ensure the first and last event_starts match the expected dates specified in the CLI arguments
            # Add start time if missing
            if data.empty or (
                data["event_start"].iloc[0] != start
                and data["event_start"].iloc[0] > start
            ):
                new_row_start = pd.DataFrame(
                    {"event_start": [start], f"{sensor_name}": [None]}
                )
                data = pd.concat([new_row_start, data], ignore_index=True)

            # Add end time if missing
            if data.empty or (
                data["event_start"].iloc[-1] != last_event_start
                and data["event_start"].iloc[-1] < last_event_start
            ):
                new_row_end = pd.DataFrame(
                    {"event_start": [last_event_start], f"{sensor_name}": [None]}
                )
                data = pd.concat([data, new_row_end], ignore_index=True)

            # Check for duplicate events
            if n_extra_points := len(data) - len(data["event_start"].unique()):
                logging.debug(
                    f"Data for {sensor_name} contains multiple beliefs about a single event. Dropping {n_extra_points} beliefs with duplicate event starts."
                )
                data = data.drop_duplicates("event_start")

            # Convert data to Darts TimeSeries
            data_darts = TimeSeries.from_dataframe(
                df=data,
                time_col="event_start",
                fill_missing_dates=True,  # Ensures all timestamps are present, filling gaps with NaNs
                freq=self.target_sensor.event_resolution,
            )
            data_darts_gaps = data_darts.gaps()

            # Fill missing values using Darts transformer
            if not data_darts_gaps.empty:
                data_darts = transformer.transform(
                    data_darts, **(interpolate_kwargs or {})
                )

                logging.debug(
                    f"Sensor '{sensor_name}' has gaps:\n{data_darts_gaps.to_string()}\n"
                    "These were filled using `pd.DataFrame.interpolate()` method."
                )
            dfs.append(data_darts)
        if len(dfs) == 1:
            data_darts = dfs[0]
        else:
            # When using future_covariate, the last day in its sensor_df extends beyond
            # the target and past regressors by "max_forecast_horizon."
            # To ensure we retain these additional future regressor records,
            # we use an outer join to merge all sensor_dfs DataFrames on the "event_start" and "belief_time" columns.

            data_darts = reduce(
                lambda left, right: left.concatenate(right),
                dfs,
            )
            data_darts = data_darts.sort_values(by=["event_start"]).reset_index(
                drop=True
            )
        return data_darts

    def _split_covariates_data(
        self,
        X_past_regressors_df: pd.DataFrame | None,
        X_future_regressors_df: pd.DataFrame | None,
        target_dataframe: pd.DataFrame,
        belief_time: pd.Timestamp,
        target_start: pd.Timestamp,
        target_end: pd.Timestamp,
        forecast_end: pd.Timestamp,
    ) -> tuple[TimeSeries | None, TimeSeries | None, TimeSeries]:
        """
        Splits past covariates, future covariates, and target data at a given timestamp.

        - Past covariates include data available before `belief_time`.
        - Future covariates include forecasted values available before `belief_time`
        and extending up to `max_forecast_horizon_in_hours`.
        - Target data includes values up to `belief_time` for model training.

        Notes:
        ------
        - **Past covariates** include only known historical values (i.e., belief time is after event time).
        - **Future covariates** include forecasts made before `belief_time` and ensure that only
        the latest available belief is selected for each future event time.

        Example:
        --------
        Given:
            - `belief_time = "2024-01-10 00:00:00"`
            - Forecast horizon: `4 hours`
            - Past covariates: Observed values before `belief_time`
            - Future covariates: Forecasts made before `belief_time` for the next 4 hours

        The function returns:
            - **past_covariates** → Values before `2024-01-10 00:00:00`
            - **future_covariates** → Forecasted values end at `2024-01-10 04:00:00`
            - **target_data** → Target values up to `2024-01-10 00:00:00

        """

        def _filter_past_covariates(df: pd.DataFrame | None):
            if df is None:
                return None

            df = df.dropna().reset_index(drop=True)
            past_data = df[
                (df["event_start"] <= target_end)
                & (df["belief_time"] > df["event_start"])
            ].copy()
            past_data = past_data.loc[
                past_data.groupby("event_start")["belief_time"].idxmax()
            ]  # get data with most recent belief_time at a certain event_start

            past_data["time_diff"] = (
                past_data["event_start"] - past_data["belief_time"]
            ).abs()
            past_data = past_data.loc[
                past_data.groupby("event_start")["time_diff"].idxmin()
            ]
            past_data = past_data.drop(columns=["time_diff"])

            columns = [x for x in df.columns if x not in ["belief_time", "source_y"]]
            past_data = past_data[columns].copy().reset_index(drop=True)

            past_covariates = self.detect_and_fill_missing_values(
                df=past_data,
                sensor_names=[r for r in self.past_regressors],
                start=target_start,
                end=target_end,
            )
            return past_covariates

        def _filter_future_covariates(df: pd.DataFrame | None):
            if df is None:
                return None

            realized_data = X_future_regressors_df[
                (X_future_regressors_df["event_start"] <= target_end)
                & (
                    X_future_regressors_df["belief_time"]
                    > X_future_regressors_df["event_start"]
                )
            ].copy()
            # Select the closest belief_time for each event_start (i.e., the most recent forecast)
            realized_data["time_diff"] = (
                realized_data["event_start"] - realized_data["belief_time"]
            ).abs()
            realized_data = realized_data.loc[
                realized_data.groupby("event_start")["time_diff"].idxmin()
            ]
            realized_data = realized_data.drop(columns=["time_diff"])

            forecast_data = X_future_regressors_df[
                (X_future_regressors_df["event_start"] > target_end)
                & (
                    X_future_regressors_df["event_start"]
                    <= target_end
                    + pd.Timedelta(hours=self.max_forecast_horizon_in_hours)
                )  # we take forecasts up to max_forecast_horizon
                & (
                    X_future_regressors_df["belief_time"]
                    <= X_future_regressors_df["event_start"]
                )  # this ensures we get forecasts
                & (
                    X_future_regressors_df["belief_time"] <= belief_time
                )  # this ensures we get forecasts made before the point we make are making the prediction
            ].copy()

            # Compute forecast horizon (in hours)
            forecast_data["forecast_horizon"] = (
                forecast_data["event_start"] - forecast_data["belief_time"]
            ).dt.total_seconds() / 3600

            # Filter forecasts within the max_forecast_horizon
            forecast_data = forecast_data[
                forecast_data["forecast_horizon"] <= self.max_forecast_horizon_in_hours
            ]

            # Select the closest belief_time for each event_start (i.e., the most recent forecast)
            forecast_data["time_diff"] = (
                forecast_data["event_start"] - forecast_data["belief_time"]
            ).abs()
            forecast_data = forecast_data.loc[
                forecast_data.groupby("event_start")["time_diff"].idxmin()
            ]
            forecast_data = forecast_data.drop(
                columns=["time_diff", "forecast_horizon"]
            )
            columns = [
                x for x in forecast_data.columns if x not in ["belief_time", "source_y"]
            ]

            forecast_data = forecast_data[columns].copy().reset_index(drop=True)
            realized_data = realized_data[columns].copy().reset_index(drop=True)

            # Concatenate realized and forecasted data
            future_covariates_df = (
                pd.concat([realized_data, forecast_data])
                .sort_values("event_start")
                .reset_index(drop=True)
            )
            forecast_data_darts = self.detect_and_fill_missing_values(
                df=forecast_data,
                sensor_names=[r for r in self.future_regressors],
                start=target_end + self.target_sensor.event_resolution,
                end=forecast_end + self.target_sensor.event_resolution,
            )

            realized_data_darts = self.detect_and_fill_missing_values(
                df=realized_data,
                sensor_names=[r for r in self.future_regressors],
                start=target_start,
                end=target_end,
            )

            past = realized_data_darts.pd_dataframe()
            future = forecast_data_darts.pd_dataframe()
            future_covariates_df = (
                pd.concat([past, future])
                .sort_index()  # sort by event_start (the index)
                .reset_index()  # reset_index
            )
            future_covariates_df.columns.name = None
            future_covariates_df = future_covariates_df.drop_duplicates(
                subset=["event_start"]
            )

            future_data_darts_end = TimeSeries.from_dataframe(
                future_covariates_df,
                time_col="event_start",
                freq=self.target_sensor.event_resolution,
            )

            return future_data_darts_end

        target_dataframe = target_dataframe.drop(columns=["belief_time"])

        target_data = self.detect_and_fill_missing_values(
            df=target_dataframe[(target_dataframe["event_start"] <= target_end)],
            sensor_names=self.target,
            start=target_start,
            end=target_end,
        )

        # Split covariate data
        past_covariates = _filter_past_covariates(X_past_regressors_df)
        future_covariates = _filter_future_covariates(X_future_regressors_df)

        return past_covariates, future_covariates, target_data
