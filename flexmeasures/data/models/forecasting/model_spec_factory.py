from typing import Union, Optional, List
from datetime import datetime, timedelta

from flask import current_app
from timetomodel import DBSeriesSpecs, ModelSpecs
from timetomodel.transforming import BoxCoxTransformation, Transformation

from flexmeasures.data.models.assets import AssetType, Asset
from flexmeasures.data.models.markets import MarketType, Market
from flexmeasures.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from flexmeasures.data.models.utils import (
    determine_asset_type_by_asset,
    determine_asset_value_class_by_asset,
)
from flexmeasures.data.models.forecasting.utils import (
    create_lags,
    set_training_and_testing_dates,
    get_query_window,
)
from flexmeasures.data.services.resources import find_closest_weather_sensor
from flexmeasures.data.config import db

"""
Here we generate an initial version of timetomodel specs, given what asset and what timing
is defined.
These specs can be customized.
"""


def create_initial_model_specs(  # noqa: C901
    generic_asset: Union[Asset, Market, WeatherSensor],
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

    generic_asset_type = determine_asset_type_by_asset(generic_asset)
    generic_asset_value_class = determine_asset_value_class_by_asset(generic_asset)

    params = _parameterise_forecasting_by_asset_and_asset_type(
        generic_asset, generic_asset_type, transform_to_normal
    )
    params.update(custom_model_params if custom_model_params is not None else {})

    lags = create_lags(
        params["n_lags"],
        generic_asset_type,
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
            generic_asset,
            generic_asset_type,
            query_window,
            forecast_horizon,
            regressor_transformation,
            transform_to_normal,
        )

    if ex_post_horizon is None:
        ex_post_horizon = timedelta(hours=0)

    outcome_var_spec = DBSeriesSpecs(
        name=generic_asset_type.name,
        db_engine=db.engine,
        query=generic_asset_value_class.make_query(
            asset_names=[generic_asset.name],
            query_window=query_window,
            belief_horizon_window=(None, ex_post_horizon),
            session=db.session,
        ),
        feature_transformation=params.get("outcome_var_transformation", None),
        interpolation_config={"method": "time"},
    )
    specs = ModelSpecs(
        outcome_var=outcome_var_spec,
        model=None,  # at least this will need to be configured still to make these specs usable!
        frequency=generic_asset.event_resolution,
        horizon=forecast_horizon,
        lags=[int(lag / generic_asset.event_resolution) for lag in lags],
        regressors=regressor_specs,
        start_of_training=training_start,
        end_of_testing=testing_end,
        ratio_training_testing_data=params["ratio_training_testing_data"],
        remodel_frequency=timedelta(days=7),
    )

    return specs


def _parameterise_forecasting_by_asset_and_asset_type(
    generic_asset: Union[Asset, Market, WeatherSensor],
    generic_asset_type: Union[AssetType, MarketType, WeatherSensorType],
    transform_to_normal: bool,
) -> dict:
    """Fill in the best parameters we know (generic or by asset (type))"""
    params = dict()

    params["training_and_testing_period"] = timedelta(days=30)
    params["ratio_training_testing_data"] = 14 / 15
    params["n_lags"] = 7
    params["resolution"] = generic_asset.event_resolution

    if transform_to_normal:
        params[
            "outcome_var_transformation"
        ] = get_normalization_transformation_by_asset_type(generic_asset_type)

    return params


def get_normalization_transformation_by_asset_type(
    generic_asset_type: Union[AssetType, MarketType, WeatherSensorType]
) -> Optional[Transformation]:
    """
    Transform data to be normal, using the BoxCox transformation. Lambda parameter is chosen
    according ot the asset type.
    """
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


def configure_regressors_for_nearest_weather_sensor(
    generic_asset,
    generic_asset_type,
    query_window,
    horizon,
    regressor_transformation,  # the regressor transformation can be passed in
    transform_to_normal,  # if not, it a normalization can be applied
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
                if len(regressor_transformation.keys()) == 0 and transform_to_normal:
                    regressor_transformation = (
                        get_normalization_transformation_by_asset_type(
                            WeatherSensorType(name=sensor_type)
                        )
                    )
                regressor_specs.append(
                    DBSeriesSpecs(
                        name=regressor_specs_name,
                        db_engine=db.engine,
                        query=Weather.make_query(
                            asset_names=[closest_sensor.name],
                            query_window=query_window,
                            belief_horizon_window=(horizon, None),
                            session=db.session,
                        ),
                        feature_transformation=regressor_transformation,
                        interpolation_config={"method": "time"},
                    )
                )

    return regressor_specs
