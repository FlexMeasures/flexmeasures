from __future__ import annotations

import sys
import logging
from datetime import datetime
from functools import reduce

import numpy as np
import pandas as pd
from darts import TimeSeries
from darts.dataprocessing.transformers import MissingValuesFiller
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
        target_sensor: Sensor,
        future_regressors: list[Sensor],
        past_regressors: list[Sensor],
        n_steps_to_predict: int,
        max_forecast_horizon: int,
        forecast_frequency: int,
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        predict_start: datetime | None = None,
        predict_end: datetime | None = None,
        missing_threshold: float = 1.0,
    ) -> None:
        self.future = future_regressors
        self.past = past_regressors
        self.n_steps_to_predict = n_steps_to_predict
        self.max_forecast_horizon = max_forecast_horizon
        # rounds up so we get the number of viewpoints, each `forecast_frequency` apart
        self.number_of_viewpoints = (
            self.n_steps_to_predict + forecast_frequency - 1
        ) // forecast_frequency
        self.event_starts_after = event_starts_after
        self.event_ends_before = event_ends_before
        self.target_sensor = target_sensor
        self.target = f"{target_sensor.name} (ID: {target_sensor.id})_target"
        self.future_regressors = [
            f"{sensor.name} (ID: {sensor.id})_FR-{idx}"
            for idx, sensor in enumerate(future_regressors)
        ]
        self.past_regressors = [
            f"{sensor.name} (ID: {sensor.id})_PR-{idx}"
            for idx, sensor in enumerate(past_regressors)
        ]
        self.predict_start = predict_start if predict_start else None
        self.predict_end = predict_end if predict_end else None
        self.max_forecast_horizon_in_hours = (
            self.max_forecast_horizon
            * self.target_sensor.event_resolution.total_seconds()
            / 3600
        )  # convert max_forecast_horizon to hours
        self.forecast_frequency = forecast_frequency
        self.missing_threshold = missing_threshold

    def load_data_all_beliefs(self) -> pd.DataFrame:
        """
        This function fetches data for each sensor.
        If a sensor is listed as a future regressor, it fetches all available beliefs (including forecasts).

        Returns:
        - pd.DataFrame: A DataFrame containing all the data from each sensor.
        """
        try:
            logging.debug(
                "Loading all data from %s",
                {
                    "Future regressors": [s.id for s in self.future],
                    "Past regressors": [s.id for s in self.past],
                    "Target": self.target_sensor.id,
                },
            )

            sensor_dfs = []
            sensor_names = self.future_regressors + self.past_regressors + [self.target]
            sensors = self.future + self.past + [self.target_sensor]
            for name, sensor in zip(sensor_names, sensors):
                logging.debug(f"Loading data for {name} (sensor ID {sensor.id})")

                sensor_event_ends_before = self.event_ends_before
                sensor_event_starts_after = self.event_starts_after

                most_recent_beliefs_only = True
                # Extend time range for future regressors
                if sensor in self.future:
                    sensor_event_ends_before = self.event_ends_before + pd.Timedelta(
                        hours=self.max_forecast_horizon_in_hours
                    )

                    most_recent_beliefs_only = False  # load all beliefs available to include forecasts available at each timestamp

                df = sensor.search_beliefs(
                    event_starts_after=sensor_event_starts_after,
                    event_ends_before=sensor_event_ends_before,
                    most_recent_beliefs_only=most_recent_beliefs_only,
                    exclude_source_types=(
                        ["forecaster"] if name == self.target else []
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
                df[["event_start", "belief_time", name]] = df[
                    ["event_start", "belief_time", "event_value"]
                ].copy()
                df_filtered = df[["event_start", "belief_time", name]]

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

    def split_data_all_beliefs(  # noqa: C901
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

                # Pre-compute per-event_start latest/closest rows
                past_latest = None
                if X_past_regressors_df is not None:
                    past_obs = X_past_regressors_df.loc[
                        X_past_regressors_df["belief_time"]
                        > X_past_regressors_df["event_start"]
                    ].copy()
                    idx = past_obs.groupby("event_start")["belief_time"].idxmax()
                    past_latest = (
                        past_obs.loc[idx]
                        .sort_values("event_start")
                        .reset_index(drop=True)
                    )
                    past_keep = [
                        c for c in past_latest.columns if c not in ("belief_time")
                    ]
                    past_latest = past_latest[past_keep]

                future_realized_latest = None
                future_all_closest = None
                if X_future_regressors_df is not None:
                    # Realized-only (belief_time > event_start): take closest per event_start
                    fr = X_future_regressors_df.loc[
                        X_future_regressors_df["belief_time"]
                        > X_future_regressors_df["event_start"]
                    ].copy()
                    fr["time_diff"] = (fr["event_start"] - fr["belief_time"]).abs()
                    idx_fr = fr.groupby("event_start")["time_diff"].idxmin()
                    fr = (
                        fr.loc[idx_fr]
                        .drop(columns=["time_diff"])
                        .sort_values("event_start")
                        .reset_index(drop=True)
                    )

                    # All beliefs: closest per event_start (used for forecast slice)
                    fa = X_future_regressors_df.copy()
                    fa["time_diff"] = (fa["event_start"] - fa["belief_time"]).abs()
                    idx_fa = fa.groupby("event_start")["time_diff"].idxmin()
                    fa = (
                        fa.loc[idx_fa]
                        .drop(columns=["time_diff"])
                        .sort_values("event_start")
                        .reset_index(drop=True)
                    )

                    keep = [c for c in fr.columns if c not in ("belief_time")]
                    future_realized_latest = fr[keep]
                    future_all_closest = fa[keep]

                y_clean = (
                    y.drop(columns=["belief_time"])
                    .sort_values("event_start")
                    .reset_index(drop=True)
                )

                # Helper function: fast closed-interval slice by event_start
                def _slice_closed(
                    df_: pd.DataFrame, start_ts: pd.Timestamp, end_ts: pd.Timestamp
                ) -> pd.DataFrame:
                    if df_ is None or df_.empty:
                        return df_.iloc[0:0].copy() if df_ is not None else None

                    # Ensure datetime dtype; then work in int64 ns for searchsorted
                    es = pd.to_datetime(df_["event_start"], errors="coerce")
                    a = es.view("int64").to_numpy()

                    lo = np.searchsorted(a, start_ts.value, side="left")
                    hi = np.searchsorted(a, end_ts.value, side="right")  # inclusive end

                    # Slice original rows by positional indices
                    out = df_.iloc[lo:hi].copy()
                    # (Optional) keep the coerced datetime back on the slice to avoid re-parsing later
                    if not out.empty:
                        out.loc[:, "event_start"] = es.iloc[lo:hi].to_numpy()
                    return out

                target_list = []
                past_covariates_list = []
                future_covariates_list = []
                belief_timestamps_list = []

                # Number of prediction iterations: all steps if predict pipeline, else just 1 (training)
                end_for_loop = self.n_steps_to_predict if is_predict_pipeline else 1

                # Loop through each simulated forecast step and increase the belief_time and target_end by 1 target sensor resolution
                for index_offset in range(0, end_for_loop, self.forecast_frequency):

                    # Move belief_time and target_end forward one resolution per step
                    delta = pd.Timedelta(
                        seconds=index_offset * target_sensor_resolution.total_seconds()
                    )
                    belief_time = first_belief_time + delta
                    target_end = first_target_end + delta
                    forecast_end = first_forecast_end + delta

                    # Target split
                    y_slice_df = _slice_closed(y_clean, target_start, target_end)
                    y_split = self.detect_and_fill_missing_values(
                        df=y_slice_df,
                        sensors=[self.target_sensor],
                        sensor_names=[self.target],
                        start=target_start,
                        end=target_end,
                    )

                    # Past covariates split
                    if past_latest is not None:
                        past_slice = _slice_closed(
                            past_latest, target_start, target_end
                        )
                        past_covariates = self.detect_and_fill_missing_values(
                            df=past_slice,
                            sensors=self.past,
                            sensor_names=self.past_regressors,
                            start=target_start,
                            end=target_end,
                        )
                    else:
                        past_covariates = None

                    # Future covariates (realized up to target_end + forecasts up to forecast_end) split
                    if (
                        future_realized_latest is not None
                        and future_all_closest is not None
                    ):
                        realized_slice = _slice_closed(
                            future_realized_latest, target_start, target_end
                        )

                        # forecasts strictly after target_end up to forecast_end
                        # and ONLY those *available at the current belief_time*
                        # (and truly forecasts: belief_time <= event_start)
                        fc_window = X_future_regressors_df.loc[
                            (X_future_regressors_df["event_start"] > target_end)
                            & (X_future_regressors_df["event_start"] <= forecast_end)
                            & (X_future_regressors_df["belief_time"] <= belief_time)
                            & (
                                X_future_regressors_df["belief_time"]
                                <= X_future_regressors_df["event_start"]
                            )
                        ].copy()

                        # for each event_start in that window, pick the latest belief before the event
                        # (closest from below wrt belief_time)
                        fc_window["time_diff"] = (
                            X_future_regressors_df.loc[fc_window.index, "event_start"]
                            - X_future_regressors_df.loc[fc_window.index, "belief_time"]
                        ).abs()
                        idx_fc = fc_window.groupby("event_start")[
                            "belief_time"
                        ].idxmax()
                        forecast_slice = (
                            fc_window.loc[idx_fc]
                            .drop(columns=["time_diff"], errors="ignore")
                            .sort_values("event_start")
                            .reset_index(drop=True)
                        )

                        # keep only value columns (drop meta)
                        keep_fc = [
                            c
                            for c in forecast_slice.columns
                            if c not in ("belief_time")
                        ]
                        forecast_slice = forecast_slice[keep_fc]

                        future_df = (
                            pd.concat(
                                [realized_slice, forecast_slice], ignore_index=True
                            )
                            .drop_duplicates(subset=["event_start"])
                            .sort_values("event_start")
                            .reset_index(drop=True)
                        )

                        future_covariates = self.detect_and_fill_missing_values(
                            df=future_df,
                            sensors=self.future,
                            sensor_names=self.future_regressors,
                            start=target_start,
                            end=forecast_end + self.target_sensor.event_resolution,
                        )

                    else:
                        future_covariates = None

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

            # Autoregressive-only case
            if not self.past and not self.future:
                logging.info("Using autoregressive forecasting.")

                y = df[["event_start", "belief_time", self.target]].copy()

                _, _, target_list, belief_timestamps_list = _generate_splits(
                    None, None, y
                )

                logging.debug("Data split successfully with autoregressive lags.")
                return None, None, target_list, belief_timestamps_list

            # With regressors
            X_past_regressors_df = (
                df[["event_start", "belief_time"] + self.past_regressors]
                if self.past_regressors
                else None
            )
            X_future_regressors_df = (
                df[["event_start", "belief_time"] + self.future_regressors]
                if self.future != []
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
        sensors: list[Sensor],
        sensor_names: list[str],
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
        - sensors (list[Sensor]): The list of sensors (used for logging).
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

        for sensor, sensor_name in zip(sensors, sensor_names):

            # check missing data before filling
            if sensor_name in df.columns:
                n_missing = df[sensor_name].isna().sum()
                total = len(df)
                missing_fraction = n_missing / total if total > 0 else 1.0

                if missing_fraction > self.missing_threshold:
                    raise ValueError(
                        f"Sensor {sensor_name} has {missing_fraction*100:.1f}% missing values "
                        f"which exceeds the allowed threshold of {self.missing_threshold*100:.1f}%"
                    )

            if df.empty:
                last_event_start = end - pd.Timedelta(
                    hours=sensor.event_resolution.total_seconds() / 3600
                )
                new_row_start = pd.DataFrame(
                    {"event_start": [start], sensor_name: [None]}
                )
                new_row_end = pd.DataFrame(
                    {"event_start": [last_event_start], sensor_name: [None]}
                )
                df = pd.concat([new_row_start, df, new_row_end], ignore_index=True)

                logging.debug(
                    f"Sensor {sensor_name} has no data from {start} to {end}. Filling with {fill}."
                )
                transformer = MissingValuesFiller(fill=float(fill))
            else:
                transformer = MissingValuesFiller(fill="auto")

            data = df.copy()

            # Convert start & end to naive UTC
            start = start.tz_localize(None)
            end = end.tz_localize(None)
            last_event_start = end

            # Ensure the first and last event_starts match the expected dates specified in the CLI arguments
            # Add start time if missing
            if data.empty or (
                data["event_start"].iloc[0] != start
                and data["event_start"].iloc[0] > start
            ):
                new_row_start = pd.DataFrame(
                    {"event_start": [start], sensor_name: [None]}
                )
                data = pd.concat([new_row_start, data], ignore_index=True)

            if data.empty or (
                data["event_start"].iloc[-1] != last_event_start
                and data["event_start"].iloc[-1] < last_event_start
            ):
                new_row_end = pd.DataFrame(
                    {"event_start": [last_event_start], sensor_name: [None]}
                )
                data = pd.concat([data, new_row_end], ignore_index=True)

            # Drop duplicate event_starts (keep first)
            if n_extra_points := len(data) - len(data["event_start"].unique()):
                logging.debug(
                    f"Data for sensor {sensor_name} contains multiple beliefs about a single event. "
                    f"Dropping {n_extra_points} beliefs with duplicate event starts."
                )
                data = data.drop_duplicates("event_start")

            # Convert to Darts TimeSeries & fill
            data_darts = TimeSeries.from_dataframe(
                df=data,
                time_col="event_start",
                fill_missing_dates=True,
                freq=self.target_sensor.event_resolution,
            )
            # Identify gaps in the time index (where timestamp rows are missing)
            data_darts_gaps = data_darts.gaps()

            missing_rows_fraction = len(data_darts_gaps) / len(data_darts)
            if missing_rows_fraction > self.missing_threshold:
                raise ValueError(
                    f"Sensor {sensor_name} has {missing_rows_fraction*100:.1f}% missing values "
                    f"which exceeds the allowed threshold of {self.missing_threshold*100:.1f}%"
                )
            if not data_darts_gaps.empty:
                data_darts = transformer.transform(
                    data_darts, **(interpolate_kwargs or {})
                )
                logging.debug(
                    f"Sensor {sensor_name} has gaps:\n{data_darts_gaps.to_string()}\n"
                    "These were filled using `pd.DataFrame.interpolate()`."
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
