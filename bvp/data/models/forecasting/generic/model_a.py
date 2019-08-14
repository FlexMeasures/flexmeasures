from typing import Tuple, List, Union, Optional
from datetime import datetime, timedelta

from flask import current_app
from timetomodel import DBSeriesSpecs, ModelSpecs
from timetomodel.transforming import BoxCoxTransformation, Transformation
from timetomodel.utils.time_utils import to_15_min_lags
from statsmodels.api import OLS

from bvp.data.models.assets import AssetType, Asset
from bvp.data.models.markets import MarketType, Market
from bvp.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from bvp.data.models.utils import (
    determine_asset_type_by_asset,
    determine_asset_value_class_by_asset,
)
from bvp.data.services.resources import find_closest_weather_sensor
from bvp.data.models.forecasting.generic.utils import check_data_availability
from bvp.data.config import db

# update this version if small things like parametrisation change
version = 2


def configure_specs(  # noqa: C901
    generic_asset: Union[Asset, Market, WeatherSensor],
    start: datetime,  # Start of forecast period
    end: datetime,  # End of forecast period
    horizon: timedelta,  # Duration between time of forecasting and time which is forecast
    ex_post_horizon: timedelta = None,
    custom_model_params: dict = None,  # overwrite forecasting params, useful for testing or experimentation
) -> Tuple[ModelSpecs, str]:
    """
    Generic OLS model for all asset types (also for markets and weather sensors) and horizons.
    Assumes a 15 minute data resolution.
    Todo: check if enough data is available both for lagged variables and regressors
    Todo: refactor assets and markets to store a list of pandas offset or timedelta instead of booleans for
          seasonality, because e.g. although solar and building assets both have daily seasonality, only the former is
          insensitive to daylight savings. Therefore: solar periodicity is 24 hours, while building periodicity is 1
          calendar day.
    """

    generic_asset_type = determine_asset_type_by_asset(generic_asset)
    generic_asset_value_class = determine_asset_value_class_by_asset(generic_asset)

    params = parameterise_forecasting_by_asset_type(generic_asset_type)
    params.update(custom_model_params if custom_model_params is not None else {})

    lags = create_lags(
        params["n_lags"], generic_asset_type, horizon, params["resolution"]
    )

    training_start, testing_end = set_training_and_testing_dates(
        start, params["training_and_testing_period"]
    )
    query_window = get_query_window(training_start, end, lags)

    regressor_transformation = {}
    if custom_model_params:
        if custom_model_params.get("regressor_transformation", None) is not None:
            regressor_transformation = custom_model_params.get(
                "regressor_transformation", {}
            )
    regressor_specs = get_regressors(
        generic_asset,
        generic_asset_type,
        query_window,
        horizon,
        regressor_transformation,
    )

    check_data_availability(
        generic_asset, generic_asset_value_class, start, end, query_window, horizon
    )

    if ex_post_horizon is None:
        ex_post_horizon = timedelta(hours=0)

    outcome_var_spec = DBSeriesSpecs(
        name=generic_asset_type.name,
        db_engine=db.engine,
        query=generic_asset_value_class.make_query(
            asset_name=generic_asset.name,
            query_window=query_window,
            horizon_window=(None, ex_post_horizon),
            rolling=True,
            session=db.session,
        ),
        feature_transformation=params["outcome_var_transformation"],
    )
    specs = ModelSpecs(
        outcome_var=outcome_var_spec,
        model=OLS,
        frequency=timedelta(minutes=15),
        horizon=horizon,
        lags=to_15_min_lags(lags),
        regressors=regressor_specs,
        start_of_training=training_start,
        end_of_testing=testing_end,
        ratio_training_testing_data=params["ratio_training_testing_data"],
        remodel_frequency=timedelta(days=7),
    )
    return specs, specs_version()


def specs_version() -> str:
    return "generic model_a (v%d)" % version


def parameterise_forecasting_by_asset_type(
    generic_asset_type: Union[AssetType, MarketType, WeatherSensorType]
) -> dict:
    """Fill in the best parameters we know (generic or by asset type)"""
    params = dict()

    params["training_and_testing_period"] = timedelta(days=30)
    params["ratio_training_testing_data"] = 14 / 15
    params["n_lags"] = 7
    params["resolution"] = timedelta(
        minutes=15
    )  # Todo: get the data resolution for the asset from asset type

    params["outcome_var_transformation"] = get_transformation_by_asset_type(
        generic_asset_type
    )

    return params


def get_transformation_by_asset_type(
    generic_asset_type: Union[AssetType, MarketType, WeatherSensorType]
) -> Optional[Transformation]:
    if isinstance(generic_asset_type, AssetType):
        if (generic_asset_type.is_consumer and not generic_asset_type.is_producer) or (
            generic_asset_type.is_producer and not generic_asset_type.is_consumer
        ):
            return BoxCoxTransformation(lambda2=0.1)
        else:
            return None
    elif isinstance(generic_asset_type, MarketType):
        return None
    elif isinstance(generic_asset_type, WeatherSensorType):
        if generic_asset_type.name in ["wind_speed", "radiation"]:
            # Values cannot be negative and are often zero
            return BoxCoxTransformation(lambda2=0.1)
        elif generic_asset_type.name == "temperature":
            # Values can be positive or negative when given in degrees Celsius, but non-negative only in Kelvin
            return BoxCoxTransformation(lambda2=273.16)
        else:
            return None
    else:
        raise TypeError("Unknown generic asset type.")


def set_training_and_testing_dates(
    start: datetime,
    training_and_testing_period: Union[timedelta, Tuple[datetime, datetime]],
) -> Tuple[datetime, datetime]:
    """Return training_start and testing_end"""
    if isinstance(training_and_testing_period, timedelta):
        return start - training_and_testing_period, start
    else:
        return training_and_testing_period[0], training_and_testing_period[1]


def get_query_window(training_start, end, lags):
    """Make sure we have enough data for lagging and forecasting"""
    if not lags:
        query_start = training_start
    else:
        query_start = training_start - max(lags)
    query_end = end
    return query_start, query_end


def create_lags(
    n_lags: int, generic_asset_type: str, horizon: timedelta, resolution: timedelta
) -> List[timedelta]:
    # List the lags for this asset
    lags = []

    # Include a zero lag in case of backwards forecasting
    # Todo: we should always take into account the latest forecast, so always append the zero lag if that belief exists
    if horizon < timedelta(hours=0):
        lags.append(timedelta(hours=0))

    # Include latest measurements
    lag_period = resolution
    number_of_nan_lags = 1 + (horizon - resolution) // lag_period
    for L in range(n_lags):
        lags.append((L + number_of_nan_lags) * lag_period)

    # Include relevant measurements given the asset's periodicity
    if hasattr(generic_asset_type, "daily_seasonality"):
        if generic_asset_type.daily_seasonality:
            lag_period = timedelta(days=1)
            number_of_nan_lags = 1 + (horizon - resolution) // lag_period
            for L in range(n_lags):
                lags.append((L + number_of_nan_lags) * lag_period)

    # Remove possible double entries
    return list(set(lags))


def get_regressors(
    generic_asset, generic_asset_type, query_window, horizon, regressor_transformation
) -> List[DBSeriesSpecs]:
    """For Assets, we use weather data as regressors. Here, we configure them."""
    regressor_specs = []
    if isinstance(generic_asset, Asset):
        sensor_types = generic_asset_type.weather_correlations
        current_app.logger.info(
            "For %s, I need sensors: %s" % (generic_asset, sensor_types)
        )
        for sensor_type in sensor_types:

            # Find nearest weather sensor
            closest_sensor = find_closest_weather_sensor(
                sensor_type, object=generic_asset
            )
            if closest_sensor is None:
                current_app.logger.warning(
                    "No sensor found of sensor type %s to use as regressor for %s."
                    % (sensor_type, generic_asset)
                )
            else:
                current_app.logger.info(
                    "Using sensor %s as regressor for %s."
                    % (sensor_type, generic_asset)
                )
                # Collect the weather data for the requested time window
                regressor_specs_name = "%s_l0" % sensor_type
                if len(regressor_transformation.keys()) == 0:
                    regressor_transformation = get_transformation_by_asset_type(
                        WeatherSensorType(name=sensor_type)
                    )
                regressor_specs.append(
                    DBSeriesSpecs(
                        name=regressor_specs_name,
                        db_engine=db.engine,
                        query=Weather.make_query(
                            asset_name=closest_sensor.name,
                            query_window=query_window,
                            horizon_window=(horizon, None),
                            rolling=True,
                            session=db.session,
                        ),
                        feature_transformation=regressor_transformation,
                    )
                )

    return regressor_specs
