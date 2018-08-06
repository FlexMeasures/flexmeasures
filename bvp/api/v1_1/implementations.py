from typing import Tuple, Union
from datetime import timedelta

from flask import current_app
from flask_json import as_json
from flask_security import current_user

from bvp.api.common.responses import (
    invalid_domain,
    request_processed,
    unrecognized_sensor,
)
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
from bvp.api.v1.implementations import collect_connection_and_value_groups
from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
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


@assets_required("market")
@optional_horizon_accepted()
def post_price_data_response(horizon, rolling):
    # Parse the entity address
    # Look for the Market object
    # Create new Price objects
    return


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
    api_policy = "create sensor if unknown"

    current_app.logger.info("POSTING")
    data_source = DataSource.query.filter(DataSource.user == current_user).one_or_none()
    weather_measurements = []
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
            for j, value in enumerate(value_group):
                dt = start + j * duration / len(value_group)
                if rolling:
                    h = horizon
                else:
                    h = horizon + j * duration / len(value_group)
                w = Weather(
                    datetime=dt,
                    value=value,
                    horizon=h,
                    sensor_id=weather_sensor.id,
                    data_source_id=data_source.id,
                )
                weather_measurements.append(w)

    # Put these into the database
    current_app.logger.info(weather_measurements)
    current_app.logger.info("SAVING TO DB...")
    db.session.bulk_save_objects(weather_measurements)
    db.session.commit()

    return request_processed()


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
