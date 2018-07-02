import isodate
from typing import Tuple, Union

from flask import request
from flask_json import as_json
from flask_security import current_user

from bvp.data.config import db
from bvp.data.models.assets import Asset, Power
from bvp.api.common.responses import (
    invalid_domain,
    invalid_role,
    invalid_timezone,
    unrecognized_connection_group,
    request_processed,
)
from bvp.data.services import get_assets
from bvp.api.common.utils.api_utils import parse_entity_address, update_beliefs
from bvp.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    connections_required,
    values_required,
    validate_entity_address,
)


@type_accepted('GetMeterDataRequest')
@units_accepted('MW')
@connections_required
@as_json
def get_meter_data_response(unit, connection_groups) -> Union[dict, Tuple[dict, int]]:
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Only supports GET requests.
    The response message has a different structure depending on:
        1) the number of connections for which meter data is requested, and
        2) whether the time window in the request maps an integer number of time slots for the meter data
    In all cases, the API defaults to use shorthand for univariate timeseries data,
    in which the data resolution can be derived by dividing the duration of the time window over the number of values.
    """
    print(request)
    from flask import current_app

    current_app.logger.info("GETTING")

    # Validate time window
    start = isodate.parse_datetime(request.args.get("start"))
    tz = start.tzinfo
    if tz is None:
        return invalid_timezone()
    duration = isodate.parse_duration(request.args.get("duration"))
    # Todo: Check whether the time window lies in the past (if so advise the user to use getPrognosis)

    # Retrieve meter data from database
    connections = connection_groups[0]  # only one connection group allowed for get_meter_data
    group = []
    for asset in get_assets():
        if asset.name in connections or str(asset.id) in connections:
            print(
                "For user %s, I chose Asset %s, id: %s"
                % (current_user, asset, asset.id)
            )
            # TODO: use bvp.data.services.get_power?
            # Maybe make it possible to return the actual DB objects we want here.
            measurement_frequency = isodate.parse_duration(
                "PT15M"
            )  # Todo: actually look up the measurement frequency
            measurements = Power.query.filter(
                (Power.datetime > start - measurement_frequency)
                & (Power.datetime < start + duration)
                & (Power.asset_id == asset.id)
            ).all()
            # Todo: Check if all the data is there, otherwise return what is known and warn the user
            start_buffer = (
                                   measurements[0].datetime + measurement_frequency - start
                           ) % measurement_frequency
            end_buffer = (
                                 start + duration - measurements[-1].datetime
                         ) % measurement_frequency
            values = [measurement.value for measurement in measurements]
            # datetimes = [isodate.datetime_isoformat(measurement.datetime) for measurement in measurements]
            # print(datetimes)
            # print(len(values))
            # TODO: convert to requested unit

            # Start building a dictionary with the response
            if start_buffer or end_buffer:  # timeseries is component-wise univariate
                timeseries = []
                if start_buffer:
                    timeseries.append(
                        dict(
                            value=values[0],
                            start=isodate.datetime_isoformat(start),
                            duration=isodate.duration_isoformat(start_buffer),
                        )
                    )
                    del values[0]
                if end_buffer:
                    temp_value = values[-1]
                    del values[-1]
                timeseries.append(
                    dict(
                        values=values,
                        start=isodate.datetime_isoformat(
                            measurements[1].datetime.astimezone(tz)
                        ),
                        duration=isodate.duration_isoformat(
                            len(values) * measurement_frequency
                        ),
                    )
                )
                if end_buffer:
                    timeseries.append(
                        dict(
                            value=temp_value,
                            start=isodate.datetime_isoformat(
                                measurements[-1].datetime.astimezone(tz)
                            ),
                            duration=isodate.duration_isoformat(end_buffer),
                        )
                    )
                group.append(dict(connection=asset.name, timeseries=timeseries))
            else:  # timeseries is univariate
                group.append(
                    dict(
                        connection=asset.name,
                        values=values,
                        start=isodate.datetime_isoformat(start),
                        duration=isodate.duration_isoformat(
                            len(values) * measurement_frequency
                        ),
                    )
                )
    if len(group) == 0:
        return unrecognized_connection_group()
    elif len(group) == 1:
        response = dict(unit=unit)
        response.update(group[0])
    else:
        response = dict(group=group, unit=unit)
    return response


@type_accepted('PostMeterDataRequest')
@units_accepted('MW')
@connections_required
@values_required
@as_json
def post_meter_data_response(unit, connection_groups, value_groups) -> Union[dict, Tuple[dict, int]]:
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Only supports POST requests.
    """

    from flask import current_app

    current_app.logger.info("POSTING")

    form = request.get_json(force=True)

    # Validate time window
    start = isodate.parse_datetime(form["start"])
    duration = isodate.parse_duration(form["duration"])
    # Todo: Check whether the time interval lies in the past
    # - Else advise the user to use postPrognosis or inform that the user is simulating the future

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
                current_app.logger.warn("Cannot parse this connection's entity address: %s" % connection)
                return invalid_domain()
            scheme_and_naming_authority, owner_id, asset_id = parse_entity_address(connection)
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
                    datetime=dt, value=value, horizon="-PT15M", asset_id=asset.id
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


@type_accepted('GetServiceRequest')
@as_json
def get_service_response(service_listing, requested_access_role) -> dict:
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
    return response
