from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from pprint import pformat
from typing import Any
import logging
import pytz

from flask import current_app
from flexmeasures.data.queries.utils import (
    simplify_index,
)
from timely_beliefs import BeliefsDataFrame
from timetomodel import ModelSpecs
from timetomodel.exceptions import MissingData, NaNData
from timetomodel.speccing import SeriesSpecs
from timetomodel.transforming import (
    BoxCoxTransformation,
    ReversibleTransformation,
    Transformation,
)
import pandas as pd

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.forecasting.utils import (
    create_lags,
    set_training_and_testing_dates,
    get_query_window,
)

"""
Here we generate an initial version of timetomodel specs, given what asset and what timing
is defined.
These specs can be customized.
"""


logger = logging.getLogger(__name__)


class TBSeriesSpecs(SeriesSpecs):
    """Compatibility for using timetomodel.SeriesSpecs with timely_beliefs.BeliefsDataFrames.

    This implements _load_series such that <time_series_class>.search is called,
    with the parameters in search_params.
    The search function is expected to return a BeliefsDataFrame.
    """

    time_series_class: Any  # with <search_fnc> method (named "search" by default)
    search_params: dict

    def __init__(
        self,
        search_params: dict,
        name: str,
        time_series_class: type | None = TimedBelief,
        search_fnc: str = "search",
        original_tz: tzinfo | None = pytz.utc,  # postgres stores naive datetimes
        feature_transformation: ReversibleTransformation | None = None,
        post_load_processing: Transformation | None = None,
        resampling_config: dict[str, Any] = None,
        interpolation_config: dict[str, Any] = None,
    ):
        super().__init__(
            name,
            original_tz,
            feature_transformation,
            post_load_processing,
            resampling_config,
            interpolation_config,
        )
        self.time_series_class = time_series_class
        self.search_params = search_params
        self.search_fnc = search_fnc

    @staticmethod
    def _extract_regressor_policy(
        search_params: dict[str, Any],
    ) -> tuple[dict[str, Any], datetime | None]:
        """Return cleaned search params and optional regressor-policy context."""
        cleaned_params = dict(search_params)
        issue_time = cleaned_params.pop("policy_issue_time", None)
        # Legacy compatibility: ignore this key if present.
        cleaned_params.pop("policy_future_horizon_floor", None)
        return cleaned_params, issue_time

    def _load_beliefs_data(self, search_params: dict[str, Any]) -> BeliefsDataFrame:
        return getattr(self.time_series_class, self.search_fnc)(**search_params)

    @staticmethod
    def _collapse_regressor_duplicates(
        df: pd.DataFrame, issue_time: pd.Timestamp
    ) -> pd.DataFrame:
        """Keep one belief per event_start with source-aware tie-breaking.

        Strategy:
        - Historical events (< issue_time): prefer source "flex.service".
        - Future events (>= issue_time): prefer source "Thiink forecaster".
        - Within same preference bucket, keep most recent belief_time.
        """
        if not df.index.has_duplicates:
            return df

        work = df.copy()
        work = work.reset_index().rename(columns={"index": "event_start"})
        work["event_start"] = pd.to_datetime(work["event_start"], utc=True)

        # Normalize source name for robust matching (source objects or plain strings).
        if "source" in work.columns:
            work["_source_name"] = work["source"].map(
                lambda s: getattr(s, "name", str(s))
            )
        else:
            work["_source_name"] = ""

        if "belief_time" in work.columns:
            work["_belief_time"] = pd.to_datetime(work["belief_time"], utc=True)
        else:
            work["_belief_time"] = pd.NaT

        historical_mask = work["event_start"] < issue_time
        preferred_hist = work["_source_name"] == "flex.service"
        preferred_future = work["_source_name"] == "Thiink forecaster"
        work["_preferred_source"] = False
        work.loc[historical_mask, "_preferred_source"] = preferred_hist[historical_mask]
        work.loc[~historical_mask, "_preferred_source"] = preferred_future[~historical_mask]

        # Deterministic tie-breaks:
        # 1) preferred source first
        # 2) most recent belief_time
        # 3) keep stable order for any remaining ties
        work = work.sort_values(
            by=["event_start", "_preferred_source", "_belief_time"],
            ascending=[True, False, False],
            kind="stable",
        )
        work = work.groupby("event_start", as_index=False).head(1)
        work = work.drop(columns=["_source_name", "_belief_time", "_preferred_source"])
        work = work.set_index("event_start")
        return work

    def _load_regressor_beliefs_split_by_issue_time(
        self,
        search_params: dict[str, Any],
        issue_time: datetime,
    ) -> BeliefsDataFrame:
        """Load regressor beliefs with policy split.

        Historical events (< issue_time) have no horizon floor.
        Future events (>= issue_time) also avoid hard horizon filtering here,
        so simulation/backfill data remains usable.
        """
        original_event_starts_after = search_params.get("event_starts_after")
        original_event_ends_before = search_params.get("event_ends_before")
        issue_time_ts = pd.Timestamp(issue_time)

        historical_params = dict(search_params)
        historical_params["horizons_at_least"] = None
        if (
            original_event_ends_before is None
            or pd.Timestamp(original_event_ends_before) > issue_time_ts
        ):
            historical_params["event_ends_before"] = issue_time_ts

        future_params = dict(search_params)
        # Keep this explicit to avoid accidental policy coupling to belief_horizon
        # values written by providers/simulations.
        future_params["horizons_at_least"] = None
        if (
            original_event_starts_after is None
            or pd.Timestamp(original_event_starts_after) < issue_time_ts
        ):
            future_params["event_starts_after"] = issue_time_ts
        if original_event_ends_before is not None:
            future_params["event_ends_before"] = original_event_ends_before

        frames = []
        if (
            original_event_starts_after is None
            or pd.Timestamp(original_event_starts_after) < issue_time_ts
        ):
            frames.append(self._load_beliefs_data(historical_params))
        if (
            original_event_ends_before is None
            or pd.Timestamp(original_event_ends_before) > issue_time_ts
        ):
            frames.append(self._load_beliefs_data(future_params))

        if not frames:
            return self._load_beliefs_data(search_params)
        if len(frames) == 1:
            return frames[0]
        merged = pd.concat(frames).sort_index()
        # If both queries include the same belief row at the boundary (DB-dependent
        # interval semantics), remove exact duplicates to keep indexes unique later.
        merged = merged.loc[~merged.index.duplicated(keep="last")]
        return merged

    def _load_series(self) -> pd.Series:
        logger.info("Reading %s data from database" % self.time_series_class.__name__)

        (
            search_params,
            issue_time,
        ) = self._extract_regressor_policy(self.search_params)
        if issue_time is not None:
            bdf: BeliefsDataFrame = self._load_regressor_beliefs_split_by_issue_time(
                search_params=search_params,
                issue_time=issue_time,
            )
        else:
            bdf = self._load_beliefs_data(search_params)
        assert isinstance(bdf, BeliefsDataFrame)
        df = simplify_index(bdf, index_levels_to_columns=["belief_time", "source"])
        if issue_time is not None:
            df = self._collapse_regressor_duplicates(df, pd.Timestamp(issue_time))
        if getattr(df.index, "tz", None) is not None and str(df.index.tz) != "UTC":
            df = df.tz_convert("UTC")
        self.check_data(df)

        if self.post_load_processing is not None:
            df = self.post_load_processing.transform_dataframe(df)

        return df["event_value"]

    def check_data(self, df: pd.DataFrame):
        """Raise error if data is empty or contains nan values.
        Here, other than in load_series, we can show the query, which is quite helpful."""
        if df.empty:
            raise MissingData(
                "No values found in database for the requested %s data. It's no use to continue I'm afraid."
                " Here's a print-out of what I tried to search for:\n\n%s\n\n"
                % (
                    self.time_series_class.__name__,
                    pformat(self.search_params, sort_dicts=False),
                )
            )
        if df.isnull().values.any():
            raise NaNData(
                "Nan values found in database for the requested %s data. It's no use to continue I'm afraid."
                " Here's a print-out of what I tried to search for:\n\n%s\n\n"
                % (
                    self.time_series_class.__name__,
                    pformat(self.search_params, sort_dicts=False),
                )
            )


def create_initial_model_specs(  # noqa: C901
    sensor: Sensor,
    forecast_start: datetime,  # Start of forecast period
    forecast_end: datetime,  # End of forecast period
    forecast_horizon: timedelta,  # Duration between time of forecasting and end time of the event that is forecast
    ex_post_horizon: timedelta | None = None,
    transform_to_normal: bool = True,
    use_regressors: bool = True,  # If false, do not create regressor specs
    use_periodicity: bool = True,  # If false, do not create lags given the asset's periodicity
    custom_model_params: dict
    | None = None,  # overwrite model params, most useful for tests or experiments
    time_series_class: type | None = TimedBelief,
) -> ModelSpecs:
    """
    Generic model specs for all asset types (also for markets and weather sensors) and horizons.
    Fills in training, testing periods, lags. Specifies input and regressor data.
    Does not fill in which model to actually use.
    TODO: check if enough data is available both for lagged variables and regressors
    TODO: refactor assets and markets to store a list of pandas offset or timedelta instead of booleans for
          seasonality, because e.g. although solar and building assets both have daily seasonality, only the former is
          insensitive to daylight savings. Therefore: solar periodicity is 24 hours, while building periodicity is 1
          calendar day.
    """

    params = _parameterise_forecasting_by_asset_and_asset_type(
        sensor, transform_to_normal
    )
    params.update(custom_model_params if custom_model_params is not None else {})

    lags = create_lags(
        params["n_lags"],
        sensor,
        forecast_horizon,
        params["resolution"],
        use_periodicity,
    )

    training_start, testing_end = set_training_and_testing_dates(
        forecast_start, params["training_and_testing_period"]
    )
    query_window = get_query_window(training_start, forecast_end, lags)

    regressor_specs = []
    regressor_transformation = {}
    if use_regressors:
        if custom_model_params:
            if custom_model_params.get("regressor_transformation", None) is not None:
                regressor_transformation = custom_model_params.get(
                    "regressor_transformation", {}
                )
        regressor_specs = configure_regressors_for_nearest_weather_sensor(
            sensor,
            query_window,
            forecast_horizon,
            forecast_start,
            regressor_transformation,
            transform_to_normal,
        )

    if ex_post_horizon is None:
        ex_post_horizon = timedelta(hours=0)

    outcome_var_spec = TBSeriesSpecs(
        name=sensor.generic_asset.generic_asset_type.name,
        time_series_class=time_series_class,
        search_params=dict(
            sensors=sensor,
            event_starts_after=query_window[0],
            event_ends_before=query_window[1],
            horizons_at_least=None,
            horizons_at_most=ex_post_horizon,
        ),
        feature_transformation=params.get("outcome_var_transformation", None),
        interpolation_config={"method": "time"},
    )
    # Set defaults if needed
    if params.get("event_resolution", None) is None:
        params["event_resolution"] = sensor.event_resolution
    if params.get("remodel_frequency", None) is None:
        params["remodel_frequency"] = timedelta(days=7)
    specs = ModelSpecs(
        outcome_var=outcome_var_spec,
        model=None,  # at least this will need to be configured still to make these specs usable!
        frequency=params[
            "event_resolution"
        ],  # todo: timetomodel doesn't distinguish frequency and resolution yet
        horizon=forecast_horizon,
        lags=[int(lag / params["event_resolution"]) for lag in lags],
        regressors=regressor_specs,
        start_of_training=training_start,
        end_of_testing=testing_end,
        ratio_training_testing_data=params["ratio_training_testing_data"],
        remodel_frequency=params["remodel_frequency"],
    )

    return specs


def _parameterise_forecasting_by_asset_and_asset_type(
    sensor: Sensor,
    transform_to_normal: bool,
) -> dict:
    """Fill in the best parameters we know (generic or by asset (type))"""
    params = dict()

    params["training_and_testing_period"] = timedelta(days=30)
    params["ratio_training_testing_data"] = 14 / 15
    params["n_lags"] = 7
    params["resolution"] = sensor.event_resolution

    if transform_to_normal:
        params[
            "outcome_var_transformation"
        ] = get_normalization_transformation_from_sensor_attributes(sensor)

    return params


def get_normalization_transformation_from_sensor_attributes(
    sensor: Sensor,
) -> Transformation | None:
    """
    Transform data to be normal, using the BoxCox transformation. Lambda parameter is chosen
    according to the asset type.
    """
    if (
        sensor.get_attribute("is_consumer") and not sensor.get_attribute("is_producer")
    ) or (
        sensor.get_attribute("is_producer") and not sensor.get_attribute("is_consumer")
    ):
        return BoxCoxTransformation(lambda2=0.1)
    elif sensor.generic_asset.generic_asset_type.name in [
        "wind speed",
        "irradiance",
    ]:
        # Values cannot be negative and are often zero
        return BoxCoxTransformation(lambda2=0.1)
    elif sensor.generic_asset.generic_asset_type.name == "temperature":
        # Values can be positive or negative when given in degrees Celsius, but non-negative only in Kelvin
        return BoxCoxTransformation(lambda2=273.16)
    else:
        return None


def configure_regressors_for_nearest_weather_sensor(
    sensor: Sensor,
    query_window,
    horizon,
    forecast_start,
    regressor_transformation,  # the regressor transformation can be passed in
    transform_to_normal,  # if not, it a normalization can be applied
) -> list[TBSeriesSpecs]:
    """We use weather data as regressors. Here, we configure them."""
    regressor_specs = []
    correlated_sensor_names = sensor.get_attribute("weather_correlations")
    if correlated_sensor_names:
        current_app.logger.info(
            "For %s, I need sensors: %s" % (sensor.name, correlated_sensor_names)
        )
        for sensor_name in correlated_sensor_names:

            # Find the nearest weather sensor
            closest_sensor = Sensor.find_closest(
                generic_asset_type_name="weather station",
                sensor_name=sensor_name,
                object=sensor,
            )
            if closest_sensor is None:
                current_app.logger.warning(
                    "No sensor found of sensor type %s to use as regressor for %s."
                    % (sensor_name, sensor.name)
                )
            else:
                current_app.logger.info(
                    "Using sensor %s as regressor for %s." % (sensor_name, sensor.name)
                )
                # Collect the weather data for the requested time window
                regressor_specs_name = "%s_l0" % sensor_name
                # Handle transformation per regressor and avoid mutating shared state across loop iterations.
                feature_transformation = regressor_transformation
                if transform_to_normal:
                    if isinstance(regressor_transformation, dict):
                        if len(regressor_transformation.keys()) == 0:
                            feature_transformation = (
                                get_normalization_transformation_from_sensor_attributes(
                                    closest_sensor,
                                )
                            )
                    elif regressor_transformation is None:
                        feature_transformation = (
                            get_normalization_transformation_from_sensor_attributes(
                                closest_sensor,
                            )
                        )
                regressor_specs.append(
                    TBSeriesSpecs(
                        name=regressor_specs_name,
                        time_series_class=TimedBelief,
                        search_params=dict(
                            sensors=closest_sensor,
                            event_starts_after=query_window[0],
                            event_ends_before=query_window[1],
                            horizons_at_least=None,
                            horizons_at_most=None,
                            policy_issue_time=forecast_start,
                        ),
                        feature_transformation=feature_transformation,
                        resampling_config={"upsampling_method": "ffill"},
                        interpolation_config={"method": "time"},
                    )
                )

    return regressor_specs
