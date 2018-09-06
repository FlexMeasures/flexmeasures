from typing import Tuple, Union
from datetime import timedelta

from flask import current_app
from flask_json import as_json
from flask_security import current_user
from sqlalchemy.exc import IntegrityError

from bvp.api.common.responses import (
    already_received_and_successfully_processed,
    invalid_domain,
    request_processed,
    unrecognized_market,
    unrecognized_sensor,
)
from bvp.api.common.utils.api_utils import save_to_database, make_forecasting_jobs
from bvp.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    assets_required,
    optional_sources_accepted,
    resolutions_accepted,
    optional_resolutions_accepted,
    optional_horizon_accepted,
    period_required,
    values_required,
    validate_entity_address,
)
from bvp.api.v1.implementations import (
    collect_connection_and_value_groups,
    create_connection_and_value_groups,
)
from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.data.models.markets import Market, Price
from bvp.data.models.weather import Weather, WeatherSensor
from bvp.data.services.resources import get_assets


@as_json
def get_connection_response():

    # Look up Asset objects
    user_assets = get_assets()

    # Return entity addresses of assets
    message = dict(connections=[asset.entity_address for asset in user_assets])
    if current_app.config.get("BVP_MODE", "") == "play":
        message["names"] = ([asset.name for asset in user_assets],)
    else:
        message["names"] = ([asset.display_name for asset in user_assets],)

    return message


@type_accepted("PostPriceDataRequest")
@units_accepted("EUR/MWh")
@assets_required("market")
@optional_horizon_accepted()
@values_required
@period_required
@resolutions_accepted(timedelta(minutes=15))
def post_price_data_response(
    unit, generic_asset_name_groups, horizon, rolling, value_groups, start, duration
):

    current_app.logger.info("POSTING PRICE DATA")
    data_source = DataSource.query.filter(DataSource.user == current_user).one_or_none()
    prices = []
    forecasting_jobs = []
    for market_group, value_group in zip(generic_asset_name_groups, value_groups):
        for market in market_group:

            # Parse the entity address
            ea = validate_entity_address(market, entity_type="market")
            if ea is None:
                current_app.logger.warn(
                    "Cannot parse this market's entity address: %s" % market
                )
                return invalid_domain()
            market_name = ea["market_name"]

            # Look for the Market object
            market = Market.query.filter(Market.name == market_name).one_or_none()
            if market is None:
                return unrecognized_market(market_name)

            # Create new Price objects
            end = start
            for j, value in enumerate(value_group):
                dt = start + j * duration / len(value_group)
                if rolling:
                    h = horizon
                else:  # Deduct the difference in end times of the individual timeslot and the timeseries duration
                    h = horizon - (
                        (start + duration) - (dt + duration / len(value_group))
                    )
                p = Price(
                    datetime=dt,
                    value=value,
                    horizon=h,
                    market_id=market.id,
                    data_source_id=data_source.id,
                )
                prices.append(p)
                end = dt

            if end > start:
                forecasting_jobs.extend(
                    make_forecasting_jobs("Price", market.id, start, end)
                )

    # Put these into the database
    current_app.logger.info("SAVING TO DB...")
    try:
        save_to_database(prices)
        save_to_database(forecasting_jobs)
        db.session.commit()
        return request_processed()
    except IntegrityError as e:
        current_app.logger.warn(e)
        db.session.rollback()

        # Allow price data to be replaced only in play mode
        if current_app.config.get("BVP_MODE", "") == "play":
            save_to_database(prices, overwrite=True)
            save_to_database(forecasting_jobs, overwrite=True)
            db.session.commit()
            return request_processed()
        else:
            return already_received_and_successfully_processed()


@type_accepted("PostWeatherDataRequest")
@units_accepted("°C")
@assets_required("sensor")
@optional_horizon_accepted()
@values_required
@period_required
@resolutions_accepted(timedelta(minutes=15))
def post_weather_data_response(
    unit, generic_asset_name_groups, horizon, rolling, value_groups, start, duration
):
    if current_app.config.get("BVP_MODE", "") == "play":
        api_policy = "create sensor if unknown"
    else:
        api_policy = "known sensors only"

    current_app.logger.info("POSTING WEATHER DATA")
    data_source = DataSource.query.filter(DataSource.user == current_user).one_or_none()
    weather_measurements = []
    forecasting_jobs = []
    for sensor_group, value_group in zip(generic_asset_name_groups, value_groups):
        for sensor in sensor_group:

            # Parse the entity address
            ea = validate_entity_address(sensor, entity_type="sensor")
            if ea is None:
                current_app.logger.warn(
                    "Cannot parse this sensor's entity address: %s" % sensor
                )
                return invalid_domain()
            weather_sensor_type_name = ea["weather_sensor_type_name"]
            latitude = ea["latitude"]
            longitude = ea["longitude"]

            # Look for the WeatherSensor object
            weather_sensor = (
                WeatherSensor.query.filter(
                    WeatherSensor.weather_sensor_type_name == weather_sensor_type_name
                )
                .filter(WeatherSensor.latitude == latitude)
                .filter(WeatherSensor.longitude == longitude)
                .one_or_none()
            )
            if weather_sensor is None:

                # either create a new weather sensor and post to that
                if api_policy is "create sensor if unknown":
                    current_app.logger.info("CREATING NEW WEATHER SENSOR...")
                    weather_sensor = WeatherSensor(
                        name="Weather sensor for %s at latitude %s and longitude %s"
                        % (weather_sensor_type_name, latitude, longitude),
                        weather_sensor_type_name=weather_sensor_type_name,
                        latitude=latitude,
                        longitude=longitude,
                    )
                    db.session.add(weather_sensor)
                    db.session.flush()  # flush so that we can reference the new object in the current db session

                # or query and return the nearest sensor and let the requesting user post to that one
                else:
                    nearest_weather_sensor = WeatherSensor.query.order_by(
                        WeatherSensor.great_circle_distance(
                            latitude=latitude, longitude=longitude
                        ).asc()
                    ).first()
                    return unrecognized_sensor(
                        nearest_weather_sensor.latitude,
                        nearest_weather_sensor.longitude,
                    )

            # Create new Weather objects
            end = start
            for j, value in enumerate(value_group):
                dt = start + j * duration / len(value_group)
                if rolling:
                    h = horizon
                else:  # Deduct the difference in end times of the individual timeslot and the timeseries duration
                    h = horizon - (
                        (start + duration) - (dt + duration / len(value_group))
                    )
                w = Weather(
                    datetime=dt,
                    value=value,
                    horizon=h,
                    sensor_id=weather_sensor.id,
                    data_source_id=data_source.id,
                )
                weather_measurements.append(w)
                end = dt

            if end > start:
                forecasting_jobs.extend(
                    make_forecasting_jobs("Weather", weather_sensor.id, start, end)
                )

    # Put these into the database
    current_app.logger.info("SAVING TO DB...")
    try:
        save_to_database(weather_measurements)
        save_to_database(forecasting_jobs)
        db.session.commit()
        return request_processed()
    except IntegrityError as e:
        current_app.logger.warn(e)
        db.session.rollback()

        # Allow meter data to be replaced only in play mode
        if current_app.config.get("BVP_MODE", "") == "play":
            save_to_database(weather_measurements, overwrite=True)
            save_to_database(forecasting_jobs, overwrite=True)
            db.session.commit()
            return request_processed()
        else:
            return already_received_and_successfully_processed()


@type_accepted("GetPrognosisRequest")
@units_accepted("MW")
@optional_resolutions_accepted("PT15M")
@assets_required("connection")
@optional_sources_accepted()
@optional_horizon_accepted()
@period_required
@as_json
def get_prognosis_response(
    unit,
    resolution,
    generic_asset_name_groups,
    horizon,
    rolling,
    start,
    duration,
    preferred_source_ids,
    fallback_source_ids,
) -> Union[dict, Tuple[dict, int]]:

    # Any prognosis made at least <horizon> before the fact
    horizon_window = (horizon, None)

    return collect_connection_and_value_groups(
        unit,
        resolution,
        horizon_window,
        start,
        duration,
        generic_asset_name_groups,
        preferred_source_ids,
        fallback_source_ids,
        rolling=rolling,
    )


@type_accepted("PostPrognosisRequest")
@units_accepted("MW")
@assets_required("connection")
@values_required
@optional_horizon_accepted(ex_post=False)
@period_required
@resolutions_accepted(timedelta(minutes=15))
@as_json
def post_prognosis_response(
    unit, generic_asset_name_groups, value_groups, horizon, rolling, start, duration
) -> Union[dict, Tuple[dict, int]]:
    """
    Store the new power values for each asset.
    """

    return create_connection_and_value_groups(
        unit, generic_asset_name_groups, value_groups, horizon, rolling, start, duration
    )
