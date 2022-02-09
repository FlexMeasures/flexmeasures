from typing import Tuple, Union
from datetime import timedelta

from flask import current_app
from flask_json import as_json
from flask_security import current_user
import timely_beliefs as tb

from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_unit,
    ResponseTuple,
    invalid_horizon,
)
from flexmeasures.api.common.utils.api_utils import (
    save_and_enqueue,
)
from flexmeasures.api.common.utils.migration_utils import get_sensor_by_unique_name
from flexmeasures.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    unit_required,
    assets_required,
    optional_user_sources_accepted,
    post_data_checked_for_required_resolution,
    get_data_downsampling_allowed,
    optional_horizon_accepted,
    optional_prior_accepted,
    period_required,
    values_required,
    valid_sensor_units,
)
from flexmeasures.api.v1.implementations import (
    collect_connection_and_value_groups,
    create_connection_and_value_groups,
)
from flexmeasures.api.common.utils.api_utils import (
    get_sensor_by_generic_asset_type_and_location,
)
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.queries.data_sources import get_or_create_source
from flexmeasures.data.services.resources import get_sensors
from flexmeasures.data.services.forecasting import create_forecasting_jobs


@as_json
def get_connection_response():

    # Look up Sensor objects
    user_sensors = get_sensors()

    # Return entity addresses of assets
    message = dict(connections=[sensor.entity_address for sensor in user_sensors])
    if current_app.config.get("FLEXMEASURES_MODE", "") == "play":
        message["names"] = [sensor.name for sensor in user_sensors]
    else:
        message["names"] = [sensor.display_name for sensor in user_sensors]

    return message


@type_accepted("PostPriceDataRequest")
@units_accepted("price", "EUR/MWh", "KRW/kWh")
@assets_required("market")
@optional_horizon_accepted(infer_missing=True, accept_repeating_interval=True)
@values_required
@period_required
@post_data_checked_for_required_resolution("market", "fm0")
def post_price_data_response(
    unit,
    generic_asset_name_groups,
    horizon,
    rolling,
    value_groups,
    start,
    duration,
    resolution,
):

    current_app.logger.info("POSTING PRICE DATA")

    data_source = get_or_create_source(current_user)
    price_df_per_market = []
    forecasting_jobs = []
    for market_group, value_group in zip(generic_asset_name_groups, value_groups):
        for market in market_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(market, entity_type="market", fm_scheme="fm0")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            market_name = ea["market_name"]

            # Look for the Sensor object
            sensor = get_sensor_by_unique_name(market_name, ["day_ahead", "tou_tariff"])
            if type(sensor) == ResponseTuple:
                # Error message telling the user what to do
                return sensor
            if unit != sensor.unit:
                return invalid_unit("%s prices" % sensor.name, [sensor.unit])

            # Create new Price objects
            beliefs = []
            for j, value in enumerate(value_group):
                dt = start + j * duration / len(value_group)
                if rolling:
                    h = horizon
                else:  # Deduct the difference in end times of the individual timeslot and the timeseries duration
                    h = horizon - (
                        (start + duration) - (dt + duration / len(value_group))
                    )
                p = TimedBelief(
                    event_start=dt,
                    event_value=value,
                    belief_horizon=h,
                    sensor=sensor,
                    source=data_source,
                )
                beliefs.append(p)
            price_df_per_market.append(tb.BeliefsDataFrame(beliefs))

            # Make forecasts, but not in play mode. Price forecasts (horizon>0) can still lead to other price forecasts,
            # by the way, due to things like day-ahead markets.
            if current_app.config.get("FLEXMEASURES_MODE", "") != "play":
                # Forecast 24 and 48 hours ahead for at most the last 24 hours of posted price data
                forecasting_jobs = create_forecasting_jobs(
                    sensor.id,
                    max(start, start + duration - timedelta(hours=24)),
                    start + duration,
                    resolution=duration / len(value_group),
                    horizons=[timedelta(hours=24), timedelta(hours=48)],
                    enqueue=False,  # will enqueue later, after saving data
                )

    return save_and_enqueue(price_df_per_market, forecasting_jobs)


@type_accepted("PostWeatherDataRequest")
@unit_required
@assets_required("sensor")
@optional_horizon_accepted(infer_missing=True, accept_repeating_interval=True)
@values_required
@period_required
@post_data_checked_for_required_resolution("weather_sensor", "fm0")
def post_weather_data_response(  # noqa: C901
    unit,
    generic_asset_name_groups,
    horizon,
    rolling,
    value_groups,
    start,
    duration,
    resolution,
):

    current_app.logger.info("POSTING WEATHER DATA")

    data_source = get_or_create_source(current_user)
    weather_df_per_sensor = []
    forecasting_jobs = []
    for sensor_group, value_group in zip(generic_asset_name_groups, value_groups):
        for sensor in sensor_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(
                    sensor, entity_type="weather_sensor", fm_scheme="fm0"
                )
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            weather_sensor_type_name = ea["weather_sensor_type_name"]
            latitude = ea["latitude"]
            longitude = ea["longitude"]

            # Check whether the unit is valid for this sensor type (e.g. no m/s allowed for temperature data)
            accepted_units = valid_sensor_units(weather_sensor_type_name)
            if unit not in accepted_units:
                return invalid_unit(weather_sensor_type_name, accepted_units)

            sensor = get_sensor_by_generic_asset_type_and_location(
                weather_sensor_type_name, latitude, longitude
            )
            if type(sensor) == ResponseTuple:
                # Error message telling the user about the nearest weather sensor they can post to
                return sensor

            # Create new Weather objects
            beliefs = []
            for j, value in enumerate(value_group):
                dt = start + j * duration / len(value_group)
                if rolling:
                    h = horizon
                else:  # Deduct the difference in end times of the individual timeslot and the timeseries duration
                    h = horizon - (
                        (start + duration) - (dt + duration / len(value_group))
                    )
                w = TimedBelief(
                    event_start=dt,
                    event_value=value,
                    belief_horizon=h,
                    sensor=sensor,
                    source=data_source,
                )
                beliefs.append(w)
            weather_df_per_sensor.append(tb.BeliefsDataFrame(beliefs))

            # make forecasts, but only if the sent-in values are not forecasts themselves (and also not in play)
            if current_app.config.get(
                "FLEXMEASURES_MODE", ""
            ) != "play" and horizon <= timedelta(
                hours=0
            ):  # Todo: replace 0 hours with whatever the moment of switching from ex-ante to ex-post is for this sensor
                forecasting_jobs.extend(
                    create_forecasting_jobs(
                        sensor.id,
                        start,
                        start + duration,
                        resolution=duration / len(value_group),
                        enqueue=False,  # will enqueue later, after saving data
                    )
                )

    return save_and_enqueue(weather_df_per_sensor, forecasting_jobs)


@type_accepted("GetPrognosisRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@optional_user_sources_accepted()
@optional_horizon_accepted(infer_missing=False, accept_repeating_interval=True)
@optional_prior_accepted(infer_missing=False)
@period_required
@get_data_downsampling_allowed("connection", "fm0")
@as_json
def get_prognosis_response(
    unit,
    resolution,
    generic_asset_name_groups,
    horizon,
    prior,
    start,
    duration,
    user_source_ids,
) -> Union[dict, Tuple[dict, int]]:

    # Any prognosis made at least <horizon> before the fact
    belief_horizon_window = (horizon, None)

    # Any prognosis made at least before <prior>
    belief_time_window = (None, prior)

    # Check the user's intention first, fall back to schedules, then forecasts, then other data from script
    source_types = ["user", "scheduling script", "forecasting script", "script"]

    return collect_connection_and_value_groups(
        unit,
        resolution,
        belief_horizon_window,
        belief_time_window,
        start,
        duration,
        generic_asset_name_groups,
        user_source_ids,
        source_types,
    )


@type_accepted("PostPrognosisRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@values_required
@optional_horizon_accepted(
    ex_post=False, infer_missing=False, accept_repeating_interval=True
)
@period_required
@post_data_checked_for_required_resolution("connection", "fm0")
@as_json
def post_prognosis_response(
    unit,
    generic_asset_name_groups,
    value_groups,
    horizon,
    rolling,
    start,
    duration,
    resolution,
) -> Union[dict, Tuple[dict, int]]:
    """
    Store the new power values for each asset.
    """

    if horizon is None:
        # API versions before v2.0 cannot handle a missing horizon, because there is no prior
        extra_info = "Please specify the horizon field using an ISO 8601 duration (such as 'PT24H')."
        return invalid_horizon(extra_info)

    return create_connection_and_value_groups(
        unit, generic_asset_name_groups, value_groups, horizon, rolling, start, duration
    )
