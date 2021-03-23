from datetime import timedelta

from flask import current_app
from flask_json import as_json
from flask_security import current_user

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
    get_or_create_user_data_source,
    get_weather_sensor_by,
    save_to_db,
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
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import Weather
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.resources import get_assets
from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)


@type_accepted("PostPriceDataRequest")
@units_accepted("price", "EUR/MWh", "KRW/kWh")
@assets_required("market")
@optional_horizon_accepted()
@optional_prior_accepted()
@values_required
@period_required
@post_data_checked_for_required_resolution("market")
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

    data_source = get_or_create_user_data_source(current_user)
    prices = []
    forecasting_jobs = []
    for market_group, event_values in zip(generic_asset_name_groups, value_groups):
        for market in market_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(market, entity_type="market")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            market_name = ea["market_name"]

            # Look for the Market object
            market = Market.query.filter(Market.name == market_name).one_or_none()
            if market is None:
                return unrecognized_market(market_name)
            elif unit != market.unit:
                return invalid_unit("%s prices" % market.display_name, [market.unit])

            # Convert to timely-beliefs terminology
            event_starts, belief_horizons = determine_belief_timing(
                event_values, start, resolution, horizon, prior, market
            )

            # Create new Price objects
            prices.extend(
                [
                    Price(
                        datetime=event_start,
                        value=event_value,
                        horizon=belief_horizon,
                        market_id=market.id,
                        data_source_id=data_source.id,
                    )
                    for event_start, event_value, belief_horizon in zip(
                        event_starts, event_values, belief_horizons
                    )
                ]
            )

            # Make forecasts, but not in play mode. Price forecasts (horizon>0) can still lead to other price forecasts,
            # by the way, due to things like day-ahead markets.
            if current_app.config.get("FLEXMEASURES_MODE", "") != "play":
                # Forecast 24 and 48 hours ahead for at most the last 24 hours of posted price data
                forecasting_jobs = create_forecasting_jobs(
                    "Price",
                    market.id,
                    max(start, start + duration - timedelta(hours=24)),
                    start + duration,
                    resolution=duration / len(event_values),
                    horizons=[timedelta(hours=24), timedelta(hours=48)],
                    enqueue=False,  # will enqueue later, only if we successfully saved prices
                )

    return save_to_db(prices, forecasting_jobs)


@type_accepted("PostWeatherDataRequest")
@unit_required
@assets_required("sensor")
@optional_horizon_accepted()
@optional_prior_accepted()
@values_required
@period_required
@post_data_checked_for_required_resolution("sensor")
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

    data_source = get_or_create_user_data_source(current_user)
    weather_measurements = []
    forecasting_jobs = []
    for sensor_group, event_values in zip(generic_asset_name_groups, value_groups):
        for sensor in sensor_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(sensor, entity_type="sensor")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            weather_sensor_type_name = ea["weather_sensor_type_name"]
            latitude = ea["latitude"]
            longitude = ea["longitude"]

            # Check whether the unit is valid for this sensor type (e.g. no m/s allowed for temperature data)
            accepted_units = valid_sensor_units(weather_sensor_type_name)
            if unit not in accepted_units:
                return invalid_unit(weather_sensor_type_name, accepted_units)

            weather_sensor = get_weather_sensor_by(
                weather_sensor_type_name, latitude, longitude
            )

            # Convert to timely-beliefs terminology
            event_starts, belief_horizons = determine_belief_timing(
                event_values, start, resolution, horizon, prior, weather_sensor
            )

            # Create new Weather objects
            weather_measurements.extend(
                [
                    Weather(
                        datetime=event_start,
                        value=event_value,
                        horizon=belief_horizon,
                        sensor_id=weather_sensor.id,
                        data_source_id=data_source.id,
                    )
                    for event_start, event_value, belief_horizon in zip(
                        event_starts, event_values, belief_horizons
                    )
                ]
            )

            # make forecasts, but only if the sent-in values are not forecasts themselves (and also not in play)
            if current_app.config.get(
                "FLEXMEASURES_MODE", ""
            ) != "play" and horizon <= timedelta(
                hours=0
            ):  # Todo: replace 0 hours with whatever the moment of switching from ex-ante to ex-post is for this generic asset
                forecasting_jobs.extend(
                    create_forecasting_jobs(
                        "Weather",
                        weather_sensor.id,
                        start,
                        start + duration,
                        resolution=duration / len(event_values),
                        horizons=[horizon],
                        enqueue=False,  # will enqueue later, only if we successfully saved weather measurements
                    )
                )

    return save_to_db(weather_measurements, forecasting_jobs)


@type_accepted("PostMeterDataRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@values_required
@optional_horizon_accepted(ex_post=True)
@optional_prior_accepted(ex_post=True)
@period_required
@post_data_checked_for_required_resolution("connection")
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
@optional_horizon_accepted(ex_post=False)
@optional_prior_accepted(ex_post=False)
@period_required
@post_data_checked_for_required_resolution("connection")
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

    data_source = get_or_create_user_data_source(current_user)
    user_assets = get_assets()
    if not user_assets:
        current_app.logger.info("User doesn't seem to have any assets")
    user_asset_ids = [asset.id for asset in user_assets]
    power_measurements = []
    forecasting_jobs = []
    for connection_group, event_values in zip(generic_asset_name_groups, value_groups):
        for connection in connection_group:

            # TODO: get asset through util function after refactoring
            # Parse the entity address
            try:
                connection = parse_entity_address(connection, entity_type="connection")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            asset_id = connection["asset_id"]

            # Look for the Asset object
            if asset_id in user_asset_ids:
                asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
            else:
                current_app.logger.warning("Cannot identify connection %s" % connection)
                return unrecognized_connection_group()

            # Validate the sign of the values (following USEF specs with positive consumption and negative production)
            if asset.is_pure_consumer and any(v < 0 for v in event_values):
                extra_info = (
                    "Connection %s is registered as a pure consumer and can only receive non-negative values."
                    % asset.entity_address
                )
                return power_value_too_small(extra_info)
            elif asset.is_pure_producer and any(v > 0 for v in event_values):
                extra_info = (
                    "Connection %s is registered as a pure producer and can only receive non-positive values."
                    % asset.entity_address
                )
                return power_value_too_big(extra_info)

            # Convert to timely-beliefs terminology
            event_starts, belief_horizons = determine_belief_timing(
                event_values, start, resolution, horizon, prior, asset
            )

            # Create new Power objects
            power_measurements.extend(
                [
                    Power(
                        datetime=event_start,
                        value=event_value
                        * -1,  # Reverse sign for FlexMeasures specs with positive production and negative consumption
                        horizon=belief_horizon,
                        asset_id=asset.id,
                        data_source_id=data_source.id,
                    )
                    for event_start, event_value, belief_horizon in zip(
                        event_starts, event_values, belief_horizons
                    )
                ]
            )

            if create_forecasting_jobs_too:
                forecasting_jobs.extend(
                    create_forecasting_jobs(
                        "Power",
                        asset_id,
                        start,
                        start + duration,
                        resolution=duration / len(event_values),
                        enqueue=False,  # will enqueue later, only if we successfully saved power measurements
                    )
                )

    return save_to_db(power_measurements, forecasting_jobs)
