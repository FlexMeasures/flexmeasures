from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta, tzinfo
from pprint import pformat
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

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.weather import WeatherSensor, Weather
from flexmeasures.data.models.utils import (
    determine_old_time_series_class_by_old_sensor,
)
from flexmeasures.data.models.forecasting.utils import (
    create_lags,
    set_training_and_testing_dates,
    get_query_window,
)
from flexmeasures.data.services.resources import find_closest_weather_sensor

"""
Here we generate an initial version of timetomodel specs, given what asset and what timing
is defined.
These specs can be customized.
"""


logger = logging.getLogger(__name__)


class TBSeriesSpecs(SeriesSpecs):
    """Compatibility for using timetomodel.SeriesSpecs with timely_beliefs.BeliefsDataFrames.

    This implements _load_series such that TimedValue.collect is called on the generic asset class,
    with the parameters in collect_params.
    The collect function is expected to return a BeliefsDataFrame.
    """

    old_time_series_data_model: Any  # with collect method
    collect_params: dict

    def __init__(
        self,
        old_time_series_class,
        collect_params: dict,
        name: str,
        original_tz: Optional[tzinfo] = pytz.utc,  # postgres stores naive datetimes
        feature_transformation: Optional[ReversibleTransformation] = None,
        post_load_processing: Optional[Transformation] = None,
        resampling_config: Dict[str, Any] = None,
        interpolation_config: Dict[str, Any] = None,
    ):
        super().__init__(
            name,
            original_tz,
            feature_transformation,
            post_load_processing,
            resampling_config,
            interpolation_config,
        )
        self.old_time_series_data_model = old_time_series_class
        self.collect_params = collect_params

    def _load_series(self) -> pd.Series:
        logger.info(
            "Reading %s data from database" % self.old_time_series_data_model.__name__
        )

        bdf: BeliefsDataFrame = self.old_time_series_data_model.collect(
            **self.collect_params
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
                " Here's a print-out of what I tried to collect:\n\n%s\n\n"
                % (
                    self.old_time_series_data_model.__name__,
                    pformat(self.collect_params, sort_dicts=False),
                )
            )
        if df.isnull().values.any():
            raise NaNData(
                "Nan values found in database for the requested %s data. It's no use to continue I'm afraid."
                " Here's a print-out of what I tried to collect:\n\n%s\n\n"
                % (
                    self.old_time_series_data_model.__name__,
                    pformat(self.collect_params, sort_dicts=False),
                )
            )


def create_initial_model_specs(  # noqa: C901
    old_sensor: Union[Asset, Market, WeatherSensor],
    forecast_start: datetime,  # Start of forecast period
    forecast_end: datetime,  # End of forecast period
    forecast_horizon: timedelta,  # Duration between time of forecasting and end time of the event that is forecast
    ex_post_horizon: timedelta = None,
    transform_to_normal: bool = True,
    use_regressors: bool = True,  # If false, do not create regressor specs
    use_periodicity: bool = True,  # If false, do not create lags given the asset's periodicity
    custom_model_params: dict = None,  # overwrite forecasting params, most useful for testing or experimentation.
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

    old_time_series_class = determine_old_time_series_class_by_old_sensor(old_sensor)
    sensor = old_sensor.corresponding_sensor

    params = _parameterise_forecasting_by_asset_and_asset_type(
        sensor, transform_to_normal
    )
    params.update(custom_model_params if custom_model_params is not None else {})

    lags = create_lags(
        params["n_lags"],
        sensor.generic_asset,
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
            sensor.generic_asset,
            query_window,
            forecast_horizon,
            regressor_transformation,
            transform_to_normal,
        )

    if ex_post_horizon is None:
        ex_post_horizon = timedelta(hours=0)

    outcome_var_spec = TBSeriesSpecs(
        name=sensor.generic_asset.generic_asset_type.name,
        old_time_series_class=old_time_series_class,
        collect_params=dict(
            old_sensor_names=[sensor.name],
            query_window=query_window,
            belief_horizon_window=(None, ex_post_horizon),
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
        ] = get_normalization_transformation_from_generic_asset_attributes(
            sensor.generic_asset
        )

    return params


def get_normalization_transformation_from_generic_asset_attributes(
    generic_asset: GenericAsset,
) -> Optional[Transformation]:
    """
    Transform data to be normal, using the BoxCox transformation. Lambda parameter is chosen
    according to the asset type.
    """
    if (
        generic_asset.get_attribute("is_consumer")
        and not generic_asset.get_attribute("is_producer")
    ) or (
        generic_asset.get_attribute("is_producer")
        and not generic_asset.get_attribute("is_consumer")
    ):
        return BoxCoxTransformation(lambda2=0.1)
    elif generic_asset.generic_asset_type.name in ["wind_speed", "radiation"]:
        # Values cannot be negative and are often zero
        return BoxCoxTransformation(lambda2=0.1)
    elif generic_asset.generic_asset_type.name == "temperature":
        # Values can be positive or negative when given in degrees Celsius, but non-negative only in Kelvin
        return BoxCoxTransformation(lambda2=273.16)
    else:
        return None


def configure_regressors_for_nearest_weather_sensor(
    generic_asset: GenericAsset,
    query_window,
    horizon,
    regressor_transformation,  # the regressor transformation can be passed in
    transform_to_normal,  # if not, it a normalization can be applied
) -> List[TBSeriesSpecs]:
    """For Assets, we use weather data as regressors. Here, we configure them."""
    regressor_specs = []
    sensor_types = generic_asset.get_attribute("weather_correlations")
    if sensor_types:
        current_app.logger.info(
            "For %s, I need sensors: %s" % (generic_asset.name, sensor_types)
        )
        for sensor_type in sensor_types:

            # Find nearest weather sensor
            closest_sensor = find_closest_weather_sensor(
                sensor_type, object=generic_asset
            )
            if closest_sensor is None:
                current_app.logger.warning(
                    "No sensor found of sensor type %s to use as regressor for %s."
                    % (sensor_type, generic_asset.name)
                )
            else:
                current_app.logger.info(
                    "Using sensor %s as regressor for %s."
                    % (sensor_type, generic_asset.name)
                )
                # Collect the weather data for the requested time window
                regressor_specs_name = "%s_l0" % sensor_type
                if len(regressor_transformation.keys()) == 0 and transform_to_normal:
                    regressor_transformation = (
                        get_normalization_transformation_from_generic_asset_attributes(
                            closest_sensor.corresponding_generic_asset,
                        )
                    )
                regressor_specs.append(
                    TBSeriesSpecs(
                        name=regressor_specs_name,
                        old_time_series_class=Weather,
                        collect_params=dict(
                            old_sensor_names=[closest_sensor.name],
                            query_window=query_window,
                            belief_horizon_window=(horizon, None),
                        ),
                        feature_transformation=regressor_transformation,
                        interpolation_config={"method": "time"},
                    )
                )

    return regressor_specs
