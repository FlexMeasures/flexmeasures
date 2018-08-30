from typing import Tuple, List, Dict, Union, Type
from datetime import datetime, timedelta

from ts_forecasting_pipeline import DBSeriesSpecs, ModelSpecs
from ts_forecasting_pipeline.speccing import BoxCoxTransformation, Transformation
from ts_forecasting_pipeline.utils import to_15_min_lags

from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.markets import MarketType, Market, Price
from bvp.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from bvp.data.config import db

# update this version if small things like parametrisation change
version = 1


def configure_specs(  # noqa: C901
    generic_asset: Union[Asset, Market, WeatherSensor],
    start: datetime,  # Start of forecast period
    end: datetime,  # End of forecast period
    training_and_testing_period: Union[timedelta, Tuple[datetime, datetime]],
    # Some duration before start or some specific period (inclusive start, exclusive end)
    horizon: timedelta,  # Duration between time of forecasting and time which is forecast
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

    generic_asset_type = determine_asset_type(generic_asset)
    generic_asset_value_class, generic_asset_class = determine_asset_value_class(
        generic_asset
    )

    params = parameterise_forecasting_for(generic_asset_type)

    lags = create_lags(
        params["n_lags"], generic_asset_type, horizon, params["resolution"]
    )

    training_start, testing_end = set_training_and_testing_dates(
        start, training_and_testing_period
    )
    query_window = get_query_window(training_start, end, lags)

    regressor_specs, regressor_transformation = get_regressors(
        generic_asset, generic_asset_type, query_window, horizon
    )

    # Check if enough data is available for training window and lagged variables, otherwise suggest new forecast period
    q = generic_asset_value_class.query.join(generic_asset_class).filter(
        generic_asset_class.name == generic_asset.name
    )
    oldest_value = q.order_by(generic_asset_value_class.datetime.asc()).first()
    newest_value = q.order_by(generic_asset_value_class.datetime.desc()).first()
    if query_window[0] < oldest_value.datetime:
        suggested_start = start + (oldest_value.datetime - query_window[0])
        raise Exception(
            "Not enough data to forecast %s for this forecast window: set start date to %s ?"
            % (generic_asset.name, suggested_start)
        )
    if query_window[1] > newest_value.datetime:
        suggested_end = end + (newest_value.datetime - query_window[1])
        raise Exception(
            "Not enough data to forecast %s for this forecast window: set end date to %s ?"
            % (generic_asset.name, suggested_end)
        )

    outcome_var_spec = DBSeriesSpecs(
        name=generic_asset_type.name,
        db_engine=db.engine,
        query=generic_asset_value_class.make_query(
            generic_asset.name,
            query_window=query_window,
            horizon_window=(None, timedelta(hours=0)),
            rolling=True,
            session=db.session,
        ),
    )
    specs = ModelSpecs(
        outcome_var=outcome_var_spec,
        model_type="OLS",
        horizon=horizon,
        lags=to_15_min_lags(lags),
        regressors=regressor_specs,
        start_of_training=training_start,
        end_of_testing=testing_end,
        ratio_training_testing_data=params["ratio_training_testing_data"],
        transformation=params["outcome_var_transformation"],
        regressor_transformation=regressor_transformation,
    )
    return specs, "generic model_a (v%d)" % version


def determine_asset_type(
    generic_asset: Union[Asset, Market, WeatherSensor]
) -> Union[AssetType, MarketType, WeatherSensorType]:
    if isinstance(generic_asset, Asset):
        return generic_asset.asset_type
    elif isinstance(generic_asset, Market):
        return generic_asset.market_type
    elif isinstance(generic_asset, WeatherSensor):
        return generic_asset.sensor_type
    else:
        raise TypeError("Unknown generic asset type.")


def determine_asset_value_class(
    generic_asset: Union[Asset, Market, WeatherSensor]
) -> Tuple[
    Type[Union[Power, Price, Weather]], Type[Union[Asset, Market, WeatherSensor]]
]:
    if isinstance(generic_asset, Asset):
        return Power, Asset
    elif isinstance(generic_asset, Market):
        return Price, Market
    elif isinstance(generic_asset, WeatherSensor):
        return Weather, WeatherSensor
    else:
        raise TypeError("Unknown generic asset type.")


def parameterise_forecasting_for(
    generic_asset_type: Union[AssetType, MarketType, WeatherSensorType]
) -> dict:
    """Fill in the best parameters we know (generic or by asset type)"""
    params = dict()

    params["ratio_training_testing_data"] = 14 / 15
    params["n_lags"] = 7
    params["resolution"] = timedelta(
        minutes=15
    )  # Todo: get the data resolution for the asset from asset type

    if isinstance(generic_asset_type, AssetType):
        params["outcome_var_transformation"] = BoxCoxTransformation(lambda2=0.1)
    elif isinstance(generic_asset_type, MarketType):
        params["outcome_var_transformation"] = None
    elif isinstance(generic_asset_type, WeatherSensorType):
        if generic_asset_type.name in ["wind_speed", "radiation"]:
            params["outcome_var_transformation"] = BoxCoxTransformation(lambda2=0.1)
        elif generic_asset_type.name == "temperature":
            params["outcome_var_transformation"] = BoxCoxTransformation(
                lambda2=273.16 + 0.1
            )
        else:
            params["outcome_var_transformation"] = None
    else:
        raise TypeError("Unknown generic asset type.")

    return params


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
    generic_asset, generic_asset_type, query_window, horizon
) -> Tuple[List[DBSeriesSpecs], Dict[str, Transformation]]:
    """For Assets, we use weather data as regressors. Here, we configure them."""
    regressor_specs = []
    regressor_transformation = {}
    if isinstance(generic_asset, Asset):
        sensor_types = generic_asset_type.weather_correlations
        for sensor_type in sensor_types:

            # Find nearest weather sensor
            closest_sensor = (
                WeatherSensor.query.filter(
                    WeatherSensor.weather_sensor_type_name == sensor_type
                )
                .order_by(
                    WeatherSensor.great_circle_distance(object=generic_asset).asc()
                )
                .first()
            )
            if closest_sensor is None:
                print("No sensor found of sensor type %s." % sensor_type)
            else:
                # Collect the weather data for the requested time window
                regressor_specs_name = "%s_l0" % sensor_type
                regressor_specs.append(
                    DBSeriesSpecs(
                        name=regressor_specs_name,
                        db_engine=db.engine,
                        query=Weather.make_query(
                            closest_sensor.name,
                            query_window=query_window,
                            horizon_window=(horizon, None),
                            rolling=True,
                            session=db.session,
                        ),
                    )
                )
                if sensor_type in [
                    "wind",
                    "radiation",
                ]:  # Values cannot be negative and are often zero
                    regressor_transformation[
                        regressor_specs_name
                    ] = BoxCoxTransformation(lambda2=0.1)
                elif (
                    sensor_type is "temperature"
                ):  # Values can be positive or negative when given in degrees Celsius, but non-negative only in Kelvin
                    #  Todo: check if unit is degrees Celsius, otherwise convert to Celsius before applying this
                    regressor_transformation[
                        regressor_specs_name
                    ] = BoxCoxTransformation(lambda2=273.16 + 0.1)

    return regressor_specs, regressor_transformation
