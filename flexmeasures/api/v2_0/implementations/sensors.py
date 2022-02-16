from datetime import timedelta

from flask import current_app
from flask_json import as_json
from flask_security import current_user
import timely_beliefs as tb

from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_horizon,
    invalid_unit,
    power_value_too_big,
    power_value_too_small,
    unrecognized_market,
    unrecognized_connection_group,
    ResponseTuple,
)
from flexmeasures.api.common.utils.api_utils import (
    get_sensor_by_generic_asset_type_and_location,
    save_and_enqueue,
    determine_belief_timing,
)
from flexmeasures.api.common.utils.validators import (
    unit_required,
    valid_sensor_units,
    type_accepted,
    units_accepted,
    assets_required,
    post_data_checked_for_required_resolution,
    optional_horizon_accepted,
    optional_prior_accepted,
    period_required,
    values_required,
)
from flexmeasures.data.queries.data_sources import get_or_create_source
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.resources import get_sensors
from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)


@type_accepted("PostPriceDataRequest")
@units_accepted("price", "EUR/MWh", "KRW/kWh")
@assets_required("market")
@optional_horizon_accepted(infer_missing=False, infer_missing_play=True)
@optional_prior_accepted(infer_missing=True, infer_missing_play=False)
@values_required
@period_required
@post_data_checked_for_required_resolution("market", "fm1")
def post_price_data_response(  # noqa C901
    unit,
    generic_asset_name_groups,
    horizon,
    prior,
    value_groups,
    start,
    duration,
    resolution,
) -> ResponseTuple:

    # additional validation, todo: to be moved into Marshmallow
    if horizon is None and prior is None:
        extra_info = "Missing horizon or prior."
        return invalid_horizon(extra_info)

    current_app.logger.info("POSTING PRICE DATA")

    data_source = get_or_create_source(current_user)
    price_df_per_market = []
    forecasting_jobs = []
    for market_group, event_values in zip(generic_asset_name_groups, value_groups):
        for market in market_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(market, entity_type="market")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            sensor_id = ea["sensor_id"]

            # Look for the Sensor object
            sensor = Sensor.query.filter(Sensor.id == sensor_id).one_or_none()
            if sensor is None:
                return unrecognized_market(sensor_id)
            elif unit != sensor.unit:
                return invalid_unit("%s prices" % sensor.name, [sensor.unit])

            # Convert to timely-beliefs terminology
            event_starts, belief_horizons = determine_belief_timing(
                event_values, start, resolution, horizon, prior, sensor
            )

            # Create new Price objects
            beliefs = [
                TimedBelief(
                    event_start=event_start,
                    event_value=event_value,
                    belief_horizon=belief_horizon,
                    sensor=sensor,
                    source=data_source,
                )
                for event_start, event_value, belief_horizon in zip(
                    event_starts, event_values, belief_horizons
                )
            ]
            price_df_per_market.append(tb.BeliefsDataFrame(beliefs))

            # Make forecasts, but not in play mode. Price forecasts (horizon>0) can still lead to other price forecasts,
            # by the way, due to things like day-ahead markets.
            if current_app.config.get("FLEXMEASURES_MODE", "") != "play":
                # Forecast 24 and 48 hours ahead for at most the last 24 hours of posted price data
                forecasting_jobs = create_forecasting_jobs(
                    sensor.id,
                    max(start, start + duration - timedelta(hours=24)),
                    start + duration,
                    resolution=duration / len(event_values),
                    horizons=[timedelta(hours=24), timedelta(hours=48)],
                    enqueue=False,  # will enqueue later, after saving data
                )

    return save_and_enqueue(price_df_per_market, forecasting_jobs)


@type_accepted("PostWeatherDataRequest")
@unit_required
@assets_required("weather_sensor")
@optional_horizon_accepted(infer_missing=False, infer_missing_play=True)
@optional_prior_accepted(infer_missing=True, infer_missing_play=False)
@values_required
@period_required
@post_data_checked_for_required_resolution("weather_sensor", "fm1")
def post_weather_data_response(  # noqa: C901
    unit,
    generic_asset_name_groups,
    horizon,
    prior,
    value_groups,
    start,
    duration,
    resolution,
) -> ResponseTuple:
    # additional validation, todo: to be moved into Marshmallow
    if horizon is None and prior is None:
        extra_info = "Missing horizon or prior."
        return invalid_horizon(extra_info)

    current_app.logger.info("POSTING WEATHER DATA")

    data_source = get_or_create_source(current_user)
    weather_df_per_sensor = []
    forecasting_jobs = []
    for sensor_group, event_values in zip(generic_asset_name_groups, value_groups):
        for sensor in sensor_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(sensor, entity_type="weather_sensor")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            weather_sensor_type_name = ea["weather_sensor_type_name"]
            latitude = ea["latitude"]
            longitude = ea["longitude"]

            # Check whether the unit is valid for this sensor type (e.g. no m/s allowed for temperature data)
            accepted_units = valid_sensor_units(weather_sensor_type_name)
            if unit not in accepted_units:
                return invalid_unit(weather_sensor_type_name, accepted_units)

            sensor: Sensor = get_sensor_by_generic_asset_type_and_location(
                weather_sensor_type_name, latitude, longitude
            )

            # Convert to timely-beliefs terminology
            event_starts, belief_horizons = determine_belief_timing(
                event_values, start, resolution, horizon, prior, sensor
            )

            # Create new Weather objects
            beliefs = [
                TimedBelief(
                    event_start=event_start,
                    event_value=event_value,
                    belief_horizon=belief_horizon,
                    sensor=sensor,
                    source=data_source,
                )
                for event_start, event_value, belief_horizon in zip(
                    event_starts, event_values, belief_horizons
                )
            ]
            weather_df_per_sensor.append(tb.BeliefsDataFrame(beliefs))

            # make forecasts, but only if the sent-in values are not forecasts themselves (and also not in play)
            if current_app.config.get(
                "FLEXMEASURES_MODE", ""
            ) != "play" and horizon <= timedelta(
                hours=0
            ):  # Todo: replace 0 hours with whatever the moment of switching from ex-ante to ex-post is for this generic asset
                forecasting_jobs.extend(
                    create_forecasting_jobs(
                        sensor.id,
                        start,
                        start + duration,
                        resolution=duration / len(event_values),
                        horizons=[horizon],
                        enqueue=False,  # will enqueue later, after saving data
                    )
                )

    return save_and_enqueue(weather_df_per_sensor, forecasting_jobs)


@type_accepted("PostMeterDataRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@values_required
@optional_horizon_accepted(ex_post=True, infer_missing=False, infer_missing_play=True)
@optional_prior_accepted(ex_post=True, infer_missing=True, infer_missing_play=False)
@period_required
@post_data_checked_for_required_resolution("connection", "fm1")
@as_json
def post_meter_data_response(
    unit,
    generic_asset_name_groups,
    value_groups,
    horizon,
    prior,
    start,
    duration,
    resolution,
) -> ResponseTuple:
    return post_power_data(
        unit,
        generic_asset_name_groups,
        value_groups,
        horizon,
        prior,
        start,
        duration,
        resolution,
        create_forecasting_jobs_too=True,
    )


@type_accepted("PostPrognosisRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@values_required
@optional_horizon_accepted(ex_post=False, infer_missing=False, infer_missing_play=False)
@optional_prior_accepted(ex_post=False, infer_missing=True, infer_missing_play=False)
@period_required
@post_data_checked_for_required_resolution("connection", "fm1")
@as_json
def post_prognosis_response(
    unit,
    generic_asset_name_groups,
    value_groups,
    horizon,
    prior,
    start,
    duration,
    resolution,
) -> ResponseTuple:
    return post_power_data(
        unit,
        generic_asset_name_groups,
        value_groups,
        horizon,
        prior,
        start,
        duration,
        resolution,
        create_forecasting_jobs_too=False,
    )


def post_power_data(
    unit,
    generic_asset_name_groups,
    value_groups,
    horizon,
    prior,
    start,
    duration,
    resolution,
    create_forecasting_jobs_too,
):

    # additional validation, todo: to be moved into Marshmallow
    if horizon is None and prior is None:
        extra_info = "Missing horizon or prior."
        return invalid_horizon(extra_info)

    current_app.logger.info("POSTING POWER DATA")

    data_source = get_or_create_source(current_user)
    user_sensors = get_sensors()
    if not user_sensors:
        current_app.logger.info("User doesn't seem to have any assets")
    user_sensor_ids = [sensor.id for sensor in user_sensors]
    power_df_per_connection = []
    forecasting_jobs = []
    for connection_group, event_values in zip(generic_asset_name_groups, value_groups):
        for connection in connection_group:

            # TODO: get asset through util function after refactoring
            # Parse the entity address
            try:
                ea = parse_entity_address(connection, entity_type="connection")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            sensor_id = ea["sensor_id"]

            # Look for the Sensor object
            if sensor_id in user_sensor_ids:
                sensor = Sensor.query.filter(Sensor.id == sensor_id).one_or_none()
            else:
                current_app.logger.warning("Cannot identify connection %s" % connection)
                return unrecognized_connection_group()

            # Validate the sign of the values (following USEF specs with positive consumption and negative production)
            if sensor.get_attribute("is_strictly_non_positive") and any(
                v < 0 for v in event_values
            ):
                extra_info = (
                    "Connection %s is registered as a pure consumer and can only receive non-negative values."
                    % sensor.entity_address
                )
                return power_value_too_small(extra_info)
            elif sensor.get_attribute("is_strictly_non_negative") and any(
                v > 0 for v in event_values
            ):
                extra_info = (
                    "Connection %s is registered as a pure producer and can only receive non-positive values."
                    % sensor.entity_address
                )
                return power_value_too_big(extra_info)

            # Convert to timely-beliefs terminology
            event_starts, belief_horizons = determine_belief_timing(
                event_values, start, resolution, horizon, prior, sensor
            )

            # Create new Power objects
            beliefs = [
                TimedBelief(
                    event_start=event_start,
                    event_value=event_value
                    * -1,  # Reverse sign for FlexMeasures specs with positive production and negative consumption
                    belief_horizon=belief_horizon,
                    sensor=sensor,
                    source=data_source,
                )
                for event_start, event_value, belief_horizon in zip(
                    event_starts, event_values, belief_horizons
                )
            ]
            power_df_per_connection.append(tb.BeliefsDataFrame(beliefs))

            if create_forecasting_jobs_too:
                forecasting_jobs.extend(
                    create_forecasting_jobs(
                        sensor_id,
                        start,
                        start + duration,
                        resolution=duration / len(event_values),
                        enqueue=False,  # will enqueue later, after saving data
                    )
                )

    return save_and_enqueue(power_df_per_connection, forecasting_jobs)
