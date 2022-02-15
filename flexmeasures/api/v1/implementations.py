import isodate
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime as datetime_type, timedelta

from flask import current_app, request
from flask_json import as_json
from flask_security import current_user
import timely_beliefs as tb

from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.queries.data_sources import get_or_create_source
from flexmeasures.data.services.resources import get_sensors
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_role,
    power_value_too_big,
    power_value_too_small,
    unrecognized_connection_group,
    request_processed,
)
from flexmeasures.api.common.utils.api_utils import (
    groups_to_dict,
    save_and_enqueue,
)
from flexmeasures.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    assets_required,
    optional_user_sources_accepted,
    post_data_checked_for_required_resolution,
    get_data_downsampling_allowed,
    optional_horizon_accepted,
    optional_prior_accepted,
    period_required,
    values_required,
)


@type_accepted("GetMeterDataRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@optional_user_sources_accepted(default_source="MDC")
@optional_horizon_accepted(
    ex_post=True, infer_missing=False, accept_repeating_interval=True
)
@optional_prior_accepted(ex_post=True, infer_missing=False)
@period_required
@get_data_downsampling_allowed("connection", "fm0")
@as_json
def get_meter_data_response(
    unit,
    resolution,
    generic_asset_name_groups,
    horizon,
    prior,
    start,
    duration,
    user_source_ids,
) -> Tuple[dict, int]:
    """
    Read out the power values for each asset.
    The response message has a different structure depending on:
        1) the number of connections for which meter data is requested, and
        2) whether the time window in the request maps an integer number of time slots for the meter data
    In all cases, the API defaults to use shorthand for univariate timeseries data,
    in which the data resolution can be derived by dividing the duration of the time window over the number of values.
    """

    # Any meter data observed at most <horizon> after the fact and not before the fact
    belief_horizon_window = (horizon, timedelta(hours=0))

    # Any meter data observed at least before <prior>
    belief_time_window = (None, prior)

    # Check the user's intention first, fall back to other data from script
    source_types = ["user", "script"]

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


@type_accepted("PostMeterDataRequest")
@units_accepted("power", "MW")
@assets_required("connection")
@values_required
@optional_horizon_accepted(
    ex_post=True, infer_missing=True, accept_repeating_interval=True
)
@period_required
@post_data_checked_for_required_resolution("connection", "fm0")
@as_json
def post_meter_data_response(
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

    return create_connection_and_value_groups(
        unit, generic_asset_name_groups, value_groups, horizon, rolling, start, duration
    )


@as_json
def get_service_response(service_listing) -> Union[dict, Tuple[dict, int]]:
    """
    Lists the available services for the public endpoint version,
    either all of them or only those that apply to the requested access role.
    """
    requested_access_role = request.args.get("access")

    response = {"version": service_listing["version"]}
    if requested_access_role:
        accessible_services = []
        for service in service_listing["services"]:
            if requested_access_role in service["access"]:
                accessible_services.append(service)
        response["services"] = accessible_services
        if not accessible_services:
            return invalid_role(requested_access_role)
    else:
        response["services"] = service_listing["services"]
    d, s = request_processed()
    return dict(**response, **d), s


def collect_connection_and_value_groups(
    unit: str,
    resolution: str,
    belief_horizon_window: Tuple[Union[None, timedelta], Union[None, timedelta]],
    belief_time_window: Tuple[Optional[datetime_type], Optional[datetime_type]],
    start: datetime_type,
    duration: timedelta,
    connection_groups: List[List[str]],
    user_source_ids: Union[int, List[int]] = None,  # None is interpreted as all sources
    source_types: List[str] = None,
) -> Tuple[dict, int]:
    """
    Code for GETting power values from the API.
    Only allows to get values from assets owned by current user.
    Returns value sign in accordance with USEF specs
    (with negative production and positive consumption).
    """
    current_app.logger.info("GETTING")
    user_sensors = get_sensors()
    if not user_sensors:
        current_app.logger.info("User doesn't seem to have any assets")
    user_sensor_ids = [sensor.id for sensor in user_sensors]

    end = start + duration
    value_groups = []
    new_connection_groups = (
        []
    )  # Each connection in the old connection groups will be interpreted as a separate group
    for connections in connection_groups:

        # Get the sensor names
        sensor_names: List[str] = []
        for connection in connections:

            # Parse the entity address
            try:
                connection_details = parse_entity_address(
                    connection, entity_type="connection", fm_scheme="fm0"
                )
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            sensor_id = connection_details["asset_id"]

            # Look for the Sensor object
            if sensor_id in user_sensor_ids:
                sensor = Sensor.query.filter(Sensor.id == sensor_id).one_or_none()
            else:
                current_app.logger.warning("Cannot identify connection %s" % connection)
                return unrecognized_connection_group()
            sensor_names.append(sensor.name)

        # Get the power values
        # TODO: fill NaN for non-existing values
        power_bdf_dict: Dict[str, tb.BeliefsDataFrame] = TimedBelief.search(
            sensor_names,
            event_starts_after=start,
            event_ends_before=end,
            resolution=resolution,
            horizons_at_least=belief_horizon_window[0],
            horizons_at_most=belief_horizon_window[1],
            beliefs_after=belief_time_window[0],
            beliefs_before=belief_time_window[1],
            user_source_ids=user_source_ids,
            source_types=source_types,
            most_recent_beliefs_only=True,
            one_deterministic_belief_per_event=True,
            sum_multiple=False,
        )
        # Todo: parse time window of power_bdf_dict, which will be different for requests that are not of the form:
        # - start is a timestamp on the hour or a multiple of 15 minutes thereafter
        # - duration is a multiple of 15 minutes
        for k, bdf in power_bdf_dict.items():
            value_groups.append(
                [x * -1 for x in bdf["event_value"].tolist()]
            )  # Reverse sign of values (from FlexMeasures specs to USEF specs)
            new_connection_groups.append(k)
    response = groups_to_dict(
        new_connection_groups, value_groups, generic_asset_type_name="connection"
    )
    response["start"] = isodate.datetime_isoformat(start)
    response["duration"] = isodate.duration_isoformat(duration)
    response["unit"] = unit  # TODO: convert to requested unit

    d, s = request_processed()
    return dict(**response, **d), s


def create_connection_and_value_groups(  # noqa: C901
    unit, generic_asset_name_groups, value_groups, horizon, rolling, start, duration
):
    """
    Code for POSTing Power values to the API.
    Only lets users post to assets they own.
    The sign of values is validated according to asset specs, but in USEF terms.
    Then, we store the reverse sign for FlexMeasures specs (with positive production
    and negative consumption).

    If power values are not forecasts, forecasting jobs are created.
    """

    current_app.logger.info("POSTING POWER DATA")

    data_source = get_or_create_source(current_user)
    user_sensors = get_sensors()
    if not user_sensors:
        current_app.logger.info("User doesn't seem to have any assets")
    user_sensor_ids = [sensor.id for sensor in user_sensors]
    power_df_per_connection = []
    forecasting_jobs = []
    for connection_group, value_group in zip(generic_asset_name_groups, value_groups):
        for connection in connection_group:

            # TODO: get asset through util function after refactoring
            # Parse the entity address
            try:
                connection = parse_entity_address(
                    connection, entity_type="connection", fm_scheme="fm0"
                )
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            sensor_id = connection["asset_id"]

            # Look for the Sensor object
            if sensor_id in user_sensor_ids:
                sensor = Sensor.query.filter(Sensor.id == sensor_id).one_or_none()
            else:
                current_app.logger.warning("Cannot identify connection %s" % connection)
                return unrecognized_connection_group()

            # Validate the sign of the values (following USEF specs with positive consumption and negative production)
            if sensor.get_attribute("is_strictly_non_positive") and any(
                v < 0 for v in value_group
            ):
                extra_info = (
                    "Connection %s is registered as a pure consumer and can only receive non-negative values."
                    % sensor.entity_address
                )
                return power_value_too_small(extra_info)
            elif sensor.get_attribute("is_strictly_non_negative") and any(
                v > 0 for v in value_group
            ):
                extra_info = (
                    "Connection %s is registered as a pure producer and can only receive non-positive values."
                    % sensor.entity_address
                )
                return power_value_too_big(extra_info)

            # Create a new BeliefsDataFrame
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
                    event_value=value
                    * -1,  # Reverse sign for FlexMeasures specs with positive production and negative consumption
                    belief_horizon=h,
                    sensor=sensor,
                    source=data_source,
                )

                assert p not in db.session
                beliefs.append(p)
            power_df_per_connection.append(tb.BeliefsDataFrame(beliefs))

            # make forecasts, but only if the sent-in values are not forecasts themselves
            if horizon <= timedelta(
                hours=0
            ):  # Todo: replace 0 hours with whatever the moment of switching from ex-ante to ex-post is for this sensor
                forecasting_jobs.extend(
                    create_forecasting_jobs(
                        sensor_id,
                        start,
                        start + duration,
                        resolution=duration / len(value_group),
                        enqueue=False,  # will enqueue later, after saving data
                    )
                )

    return save_and_enqueue(power_df_per_connection, forecasting_jobs)
