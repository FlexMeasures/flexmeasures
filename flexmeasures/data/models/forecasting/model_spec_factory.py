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

    def _load_series(self) -> pd.Series:
        logger.info("Reading %s data from database" % self.time_series_class.__name__)

        bdf: BeliefsDataFrame = getattr(self.time_series_class, self.search_fnc)(
            **self.search_params
        )
        assert isinstance(bdf, BeliefsDataFrame)
        df = simplify_index(bdf)
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
                if len(regressor_transformation.keys()) == 0 and transform_to_normal:
                    regressor_transformation = (
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
                            horizons_at_least=horizon,
                            horizons_at_most=None,
                        ),
                        feature_transformation=regressor_transformation,
                        interpolation_config={"method": "time"},
                    )
                )

    return regressor_specs
