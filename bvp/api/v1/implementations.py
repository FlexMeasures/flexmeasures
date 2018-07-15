import isodate
from typing import List, Tuple, Union
from datetime import datetime as datetime_type, timedelta

from flask_json import as_json
from flask_security import current_user
from isodate import parse_duration

from bvp.data.config import db
from bvp.data.models.assets import Asset, Power
from bvp.api.common.responses import (
    invalid_domain,
    invalid_role,
    unrecognized_connection_group,
    request_processed,
)
from bvp.data.services.resources import get_assets
from bvp.api.common.utils.api_utils import (
    parse_entity_address,
    update_beliefs,
    groups_to_dict,
)
from bvp.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    connections_required,
    optional_sources_accepted,
    optional_resolutions_accepted,
    optional_horizon_accepted,
    period_required,
    values_required,
    validate_entity_address,
)


@type_accepted("GetMeterDataRequest")
@units_accepted("MW")
@optional_resolutions_accepted("PT15M")
@connections_required
@optional_sources_accepted(preferred_source="MDC")
@optional_horizon_accepted("-PT15M")
@period_required
@as_json
def get_meter_data_response(
    unit,
    resolution,
    connection_groups,
    horizon,
    start,
    duration,
    preferred_source_ids,
    fallback_source_ids,
) -> Tuple[dict, int]:
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Only supports GET requests.
    The response message has a different structure depending on:
        1) the number of connections for which meter data is requested, and
        2) whether the time window in the request maps an integer number of time slots for the meter data
    In all cases, the API defaults to use shorthand for univariate timeseries data,
    in which the data resolution can be derived by dividing the duration of the time window over the number of values.
    """

    return collect_connection_and_value_groups(
        unit,
        resolution,
        connection_groups,
        horizon,
        start,
        duration,
        preferred_source_ids,
        fallback_source_ids,
    )


@type_accepted("PostMeterDataRequest")
@units_accepted("MW")
@connections_required
@values_required
@period_required
@as_json
def post_meter_data_response(
    unit, connection_groups, value_groups, start, duration
) -> Union[dict, Tuple[dict, int]]:
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Only supports POST requests.
    """

    from flask import current_app

    current_app.logger.info("POSTING")

    # Abstract the assets from the message (listed in one of the following ways)
    # - value of 'connection' key (for a single asset)
    # - values of 'connections' key (for multiple assets that have the same timeseries data)
    # - values of the 'connection' and/or 'connections' keys listed under the 'groups' key
    #   (for multiple assets with different timeseries data)

    user_assets = get_assets()
    if not user_assets:
        current_app.logger.info("User doesn't seem to have any assets")
    # user_asset_names = [asset.name for asset in user_assets]
    user_asset_ids = [asset.id for asset in user_assets]
    power_measurements = []
    for connection_group, value_group in zip(connection_groups, value_groups):
        for connection in connection_group:

            # Look for the Asset object
            connection = validate_entity_address(connection)
            if not connection:
                current_app.logger.warn(
                    "Cannot parse this connection's entity address: %s" % connection
                )
                return invalid_domain()
            scheme_and_naming_authority, owner_id, asset_id = parse_entity_address(
                connection
            )
            if asset_id in user_asset_ids:
                asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
            # elif current_app.env == 'testing' and isinstance(asset_id, str) and asset_id in user_asset_names:
            #     asset = Asset.query.filter(Asset.name == asset_id).one_or_none()
            else:
                current_app.logger.warn("Cannot identify connection %s" % connection)
                return unrecognized_connection_group()

            # Create new Power objects
            for j, value in enumerate(value_group):
                dt = start + j * duration / len(value_group)
                # Todo: determine horizon based on message contents
                p = Power(
                    datetime=dt,
                    value=value,
                    horizon=parse_duration("-PT15M"),
                    asset_id=asset.id,
                    data_source=current_user.id,
                )
                power_measurements.append(p)

    # Put these into the database
    current_app.logger.info(power_measurements)
    current_app.logger.info("SAVING TO DB...")
    db.session.bulk_save_objects(power_measurements)
    db.session.commit()

    # Store the data in the power forecasts table
    # - This represents the belief states
    update_beliefs()

    # Optionally update the measurements table
    # - If the mdc called, update the measurements table and verify the measurements
    # - Else (if not the mdc) if the measurements are not yet verified, update the measurements table
    # - Else do not update the measurements table and warn the user about the verification (only mdc can overwrite)
    return request_processed()


@as_json
def get_service_response(
    service_listing, requested_access_role
) -> Union[dict, Tuple[dict, int]]:
    """
    Lists the available services for the public endpoint version,
    either all of them or only those that apply to the requested access role.
    """

    response = {"type": "GetServiceResponse", "version": service_listing["version"]}
    if requested_access_role:
        accessible_services = []
        for service in service_listing["services"]:
            if requested_access_role in service["access"]:
                accessible_services.append(service)
        response["services"] = accessible_services
        if not accessible_services:
            response["message"] = invalid_role(requested_access_role)
    else:
        response["services"] = service_listing["services"]
    d, s = request_processed()
    return dict(**response, **d), s


def collect_connection_and_value_groups(
    unit: str,
    resolution: str,
    connection_groups: List[List[str]],
    horizon: timedelta,
    start: datetime_type,
    duration: timedelta,
    preferred_source_ids: {
        Union[int, List[int]]
    } = None,  # None is interpreted as all sources
    fallback_source_ids: Union[
        int, List[int]
    ] = -1,  # An id = -1 is interpreted as no sources
) -> Tuple[dict, int]:
    from flask import current_app

    current_app.logger.info("GETTING")

    from flask import current_app

    # Todo: if resolution is specified, it should be converted properly to a pandas dataframe frequency
    if resolution == "PT15M":
        resolution = "15T"

    user_assets = get_assets()
    if not user_assets:
        current_app.logger.info("User doesn't seem to have any assets")
    # user_asset_names = [asset.name for asset in user_assets]
    user_asset_ids = [asset.id for asset in user_assets]

    end = start + duration
    value_groups = []
    new_connection_groups = []  # Each connection in the old connection groups will be interpreted as a separate group
    for group in connection_groups:
        asset_names = []
        for connection in group:

            # Look for the Asset object
            connection = validate_entity_address(connection)
            if not connection:
                current_app.logger.warn(
                    "Cannot parse this connection's entity address: %s" % connection
                )
                return invalid_domain()

            scheme_and_naming_authority, owner_id, asset_id = parse_entity_address(
                connection
            )
            if asset_id in user_asset_ids:
                asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
            else:
                current_app.logger.warn("Cannot identify connection %s" % connection)
                return unrecognized_connection_group()

            asset_names.append(asset.name)
        group_response = {"connections": group}
        ts_df_or_dict = Power.collect(
            generic_asset_names=asset_names,
            query_window=(start, end),
            resolution=resolution,
            horizon_window=(horizon, horizon),
            preferred_source_ids=preferred_source_ids,
            fallback_source_ids=fallback_source_ids,
            sum_multiple=False,
        )
        if isinstance(ts_df_or_dict, dict):
            for k, v in ts_df_or_dict.items():
                value_groups.append(v.y.tolist())
                new_connection_groups.append(k)
        elif ts_df_or_dict.empty:
            group_response["values"] = []
            value_groups.append([])
            new_connection_groups.append(group)
        else:
            group_response["values"] = ts_df_or_dict.y.tolist()
            value_groups.append(ts_df_or_dict.y.tolist())
            new_connection_groups.append(group)

    response = groups_to_dict(new_connection_groups, value_groups)
    response["start"] = isodate.datetime_isoformat(start)
    response["duration"] = isodate.duration_isoformat(duration)
    response["unit"] = unit  # TODO: convert to requested unit

    d, s = request_processed()
    return dict(**response, **d), s
