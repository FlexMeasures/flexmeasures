from datetime import timedelta

from flask import current_app
from flask_security import current_user

from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_horizon,
    invalid_unit,
    unrecognized_market,
)
from flexmeasures.api.common.utils.api_utils import (
    get_or_create_user_data_source,
    get_weather_sensor_by,
    save_to_db,
    determine_belief_horizons,
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
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import Weather
from flexmeasures.data.services.forecasting import create_forecasting_jobs
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
):

    # additional validation, todo: to be moved into Marshmallow
    if horizon is None and prior is None:
        extra_info = "Missing horizon or prior."
        return invalid_horizon(extra_info)

    current_app.logger.info("POSTING PRICE DATA")

    data_source = get_or_create_user_data_source(current_user)
    prices = []
    forecasting_jobs = []
    for market_group, value_group in zip(generic_asset_name_groups, value_groups):
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
            event_starts, event_values, belief_horizons = determine_belief_horizons(
                value_group, start, resolution, horizon, prior, market
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
                    resolution=duration / len(value_group),
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
):
    # additional validation, todo: to be moved into Marshmallow
    if horizon is None and prior is None:
        extra_info = "Missing horizon or prior."
        return invalid_horizon(extra_info)

    current_app.logger.info("POSTING WEATHER DATA")
    data_source = get_or_create_user_data_source(current_user)
    weather_measurements = []
    forecasting_jobs = []
    for sensor_group, value_group in zip(generic_asset_name_groups, value_groups):
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
            event_starts, event_values, belief_horizons = determine_belief_horizons(
                value_group, start, resolution, horizon, prior, weather_sensor
            )

            # Create new Weather objects
            weather_measurements.extend(
                [
                    Weather(
                        datetime=event_start,
                        value=event_value,
                        horizon=belief_horizon,
                        market_id=weather_sensor.id,
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
                        resolution=duration / len(value_group),
                        horizons=[horizon],
                        enqueue=False,  # will enqueue later, only if we successfully saved weather measurements
                    )
                )

    return save_to_db(weather_measurements, forecasting_jobs)
