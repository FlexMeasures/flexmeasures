from typing import Tuple, Union
import isodate
from flask import request
from flask_json import as_json
from flask_security import auth_token_required, current_user

from bvp.data.config import db
from bvp.data.models.assets import Asset, Power
# from bvp.data.models.user import User
from bvp.api import ma, bvp_api
from bvp.api.endpoints.service import service_access
from bvp.api.common.utils import sender_has_allowed_role, message_has_allowed_unit, \
    parse_asset_identifier
from bvp.api.common.responses import invalid_domain, invalid_sender, invalid_timezone, invalid_unit, \
    ptus_incomplete, unrecognized_connection_group
from bvp.data.services import get_assets


class PowerSchema(ma.ModelSchema):
    """For some neat tricks, read
    https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#overriding-generated-fields
    e.g. for getting other asset info in there
    """

    class Meta:
        model = Power
        fields = ('datetime', 'value')


@bvp_api.route('/api/getMeterData', methods=["GET"])
@auth_token_required
@as_json
def get_meter_data() -> Union[dict, Tuple[dict, int]]:
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    The response message has a different structure depending on:
        1) the number of connections for which meter data is requested, and
        2) whether the time window in the request maps an integer number of time slots for the meter data
    In all cases, the API defaults to use shorthand for univariate timeseries data,
    in which the data resolution can be derived by dividing the duration of the time window over the number of values.
    """

    from flask import current_app
    current_app.logger.info("GETTING")

    # Todo: Check version

    # Check whether the user has the proper role
    allowed_roles = service_access('getMeterData')
    if not sender_has_allowed_role(current_user, allowed_roles + ["admin"]):
        return invalid_sender(current_user, allowed_roles), 401

    # Validate time window
    start = isodate.parse_datetime(request.args.get('start'))
    tz = start.tzinfo
    if tz is None:
        return invalid_timezone(), 400
    duration = isodate.parse_duration(request.args.get('duration'))
    # Todo: Check whether the time window lies in the past (if so advise the user to use getPrognosis)

    # Validate unit
    unit = request.args.get('unit')
    if not message_has_allowed_unit(unit):
        return invalid_unit(), 400

    # Validate connections
    connections = request.args.get('connections')
    if connections is None:
        connection = request.args.get('connection')
        if connection is None:
            return unrecognized_connection_group(), 400
        connections = [connection]

    # Retrieve meter data from database
    group = []
    for asset in get_assets():
        if asset.name in connections or str(asset.id) in connections:
            print("For user %s, I chose Asset %s, id: %s" % (current_user, asset, asset.id))
            # TODO: use bvp.data.services.get_power?
            # Maybe make it possible to return the actual DB objects we want here.
            measurement_frequency = isodate.parse_duration('PT15M')  # Todo: actually look up the measurement frequency
            measurements = Power.query.filter((Power.datetime > start - measurement_frequency)
                                              & (Power.datetime < start + duration)
                                              & (Power.asset_id == asset.id)).all()
            # Todo: Check if all the data is there, otherwise return what is known and warn the user
            start_buffer = (measurements[0].datetime + measurement_frequency - start) % measurement_frequency
            end_buffer = (start + duration - measurements[-1].datetime) % measurement_frequency
            values = [measurement.value for measurement in measurements]
            # datetimes = [isodate.datetime_isoformat(measurement.datetime) for measurement in measurements]
            # print(datetimes)
            # print(len(values))
            # TODO: convert to requested unit

            # Start building a dictionary with the response
            if start_buffer or end_buffer:  # timeseries is component-wise univariate
                timeseries = []
                if start_buffer:
                    timeseries.append(dict(value=values[0],
                                           start=isodate.datetime_isoformat(start),
                                           duration=isodate.duration_isoformat(start_buffer)))
                    del values[0]
                if end_buffer:
                    temp_value = values[-1]
                    del values[-1]
                timeseries.append(dict(values=values,
                                       start=isodate.datetime_isoformat(measurements[1].datetime.astimezone(tz)),
                                       duration=isodate.duration_isoformat(len(values) * measurement_frequency)))
                if end_buffer:
                    timeseries.append(dict(value=temp_value,
                                           start=isodate.datetime_isoformat(measurements[-1].datetime.astimezone(tz)),
                                           duration=isodate.duration_isoformat(end_buffer)))
                group.append(dict(connection=asset.name,
                                  timeseries=timeseries))
            else:  # timeseries is univariate
                group.append(dict(connection=asset.name,
                                  values=values,
                                  start=isodate.datetime_isoformat(start),
                                  duration=isodate.duration_isoformat(len(values) * measurement_frequency)))
    if len(group) == 0:
        return unrecognized_connection_group(), 400
    elif len(group) == 1:
        response = dict(type='GetMeterDataResponse',
                        unit=unit)
        response.update(group[0])
    else:
        response = dict(type='GetMeterDataResponse',
                        group=group,
                        unit=unit)
    return response


@bvp_api.route('/api/postMeterData', methods=["POST"])
@auth_token_required
@as_json
def post_meter_data() -> Union[dict, Tuple[dict, int]]:
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    """

    from flask import current_app
    current_app.logger.info("POSTING")

    # Check whether the given api version is known
    # - Else list the known api versions

    # Check whether the user has the proper role
    allowed_roles = service_access('postMeterData')
    validated = sender_has_allowed_role(current_user, allowed_roles + ["admin"])
    if validated is False:
        current_app.logger.warn("User role is not allowed for this service")
        return invalid_sender(current_user, allowed_roles), 401

    form = request.get_json(force=True)

    # # The API will be more forgiving when in simulation mode
    # simulation = False
    # if 'simulation' in form:
    #     if form['simulation'] in ['True', 'true', 'Y', 'y', 'Yes', 'yes']:
    #         simulation = True

    # Validate time window
    start = isodate.parse_datetime(form['start'])
    duration = isodate.parse_duration(form['duration'])
    # Todo: Check whether the time interval lies in the past
    # - Else advise the user to use postPrognosis or inform that the user is simulating the future

    # Validate unit
    unit = form['unit']
    if not message_has_allowed_unit(unit):
        return invalid_unit(), 400

    # Abstract the assets from the message (listed in one of the following ways)
    # - value of 'connection' key (for a single asset)
    # - values of 'connections' key (for multiple assets that have the same timeseries data)
    # - values of the 'connection' and/or 'connections' keys listed under the 'groups' key
    #   (for multiple assets with different timeseries data)
    if 'connection' in form:
        assets = form['connection']
        if 'value' in form:
            values = form['value']
        elif 'values' in form:
            values = form['values']
        else:
            return ptus_incomplete(), 400
    elif 'connections' in form:
        assets = form['connections']
        if 'value' in form:
            values = form['value']
        elif 'values' in form:
            values = form['values']
        else:
            return ptus_incomplete(), 400
    elif 'groups' in form:
        assets = []
        values = []
        for group in form['groups']:
            if 'connection' in group:
                assets.append(group['connection'])
                if 'value' in group:
                    values.append(group['value'])
                elif 'values' in group:
                    values.append(group['values'])
                else:
                    return ptus_incomplete(), 400
            elif 'connections' in group:
                assets.append(group['connections'])
                if 'value' in group:
                    values.append(group['value'])
                elif 'values' in group:
                    values.append(group['values'])
                else:
                    return ptus_incomplete(), 400
            else:
                current_app.logger.warn("Group %s missing connection(s)" % group)
                return unrecognized_connection_group(), 400
    else:
        current_app.logger.warn("Form missing connection(s) or group.")
        return unrecognized_connection_group(), 400

    user_assets = get_assets()
    if not user_assets:
        current_app.logger.info("User doesn't seem to have any assets")
    user_asset_names = [asset.name for asset in user_assets]
    user_asset_ids = [asset.id for asset in user_assets]
    power_measurements = []
    if 'groups' in form:
        assets_and_values = zip(assets, values)
    else:
        assets_and_values = zip([assets], [values])
    for asset_group, values_for_asset_group in assets_and_values:
        if isinstance(asset_group, list):
            for asset in asset_group:
                if asset.count(":") > 2:  # TODO: improve, use regex
                    return invalid_domain(), 400
                scheme_and_naming_authority, owner, asset = parse_asset_identifier(asset)
                if asset in user_asset_names:
                    asset = user_assets[user_asset_names.index(asset)]
                elif asset in user_asset_ids:
                    asset = user_assets[user_asset_ids.index(asset)]
                else:
                    current_app.logger.warn("Cannot identify %s in connection group" % asset)
                    return unrecognized_connection_group(), 400
                db_asset = (
                    Asset.query.filter(Asset.name == asset.name).one_or_none()
                )
                for j, value in enumerate(values_for_asset_group):
                    dt = start + j * duration / len(values_for_asset_group)
                    p = Power(datetime=dt, value=value, asset_id=db_asset.id)
                    power_measurements.append(p)
        else:
            asset = asset_group
            scheme_and_naming_authority, owner, asset = parse_asset_identifier(asset)
            if asset in user_asset_names:
                asset = user_assets[user_asset_names.index(asset)]
            elif asset in user_asset_ids:
                asset = user_assets[user_asset_ids.index(asset)]
            else:
                current_app.logger.warn("Cannot identify %s" % asset)
                return unrecognized_connection_group(), 400
            db_asset = (
                Asset.query.filter(Asset.name == asset.name).one_or_none()
            )
            for j, value in enumerate(values_for_asset_group):
                dt = start + j * duration / len(values_for_asset_group)
                p = Power(datetime=dt, value=value, asset_id=db_asset.id)
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
    response = dict(result='temp',
                    status=[p.serialize() for p in power_measurements],
                    message="We'll be trying to save this into our database.")

    return response


def update_beliefs():
    """
    Store the data in the power forecasts table.
    """
    return
