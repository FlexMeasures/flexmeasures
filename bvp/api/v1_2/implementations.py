from datetime import timedelta

import isodate
from flask_json import as_json
from flask import request, current_app

from bvp.api.common.responses import (
    invalid_domain,
    invalid_datetime,
    invalid_timezone,
    request_processed,
    unrecognized_event,
    unrecognized_connection_group,
    outdated_event_id,
    ptus_incomplete,
)
from bvp.api.common.utils.api_utils import groups_to_dict, get_form_from_request
from bvp.api.common.utils.validators import (
    type_accepted,
    assets_required,
    period_required,
    usef_roles_accepted,
    validate_entity_address,
    units_accepted,
    parse_isodate_str,
)
from bvp.data.models.assets import Asset
from bvp.data.models.planning.battery import schedule_battery
from bvp.data.models.markets import Market
from bvp.data.services.resources import has_assets, can_access_asset


@type_accepted("GetDeviceMessageRequest")
@assets_required("event")
@period_required
@as_json
def get_device_message_response(generic_asset_name_groups, start, duration):

    resolution = timedelta(minutes=15)
    unit = "MW"

    if not has_assets():
        current_app.logger.info("User doesn't seem to have any assets.")

    # Look for the Market object
    market = Market.query.filter(Market.name == "epex_da").one_or_none()

    value_groups = []
    new_event_groups = []
    for event_group in generic_asset_name_groups:
        for event in event_group:

            # Parse the entity address
            ea = validate_entity_address(event, entity_type="event")
            if ea is None:
                current_app.logger.warn(
                    "Cannot parse this event's entity address: %s" % event
                )
                return invalid_domain()
            asset_id = ea["asset_id"]
            event_id = ea["event_id"]
            event_type = ea["event_type"]

            # Look for the Asset object
            asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
            if asset is None or not can_access_asset(asset):
                current_app.logger.warn(
                    "Cannot identify asset %s given the event." % event
                )
                return unrecognized_connection_group()
            if event_type != "soc" or event_id != asset.soc_udi_event_id:
                return unrecognized_event(event_id, event_type)

            # Schedule the asset
            value_groups.append(
                schedule_battery(
                    asset, market, start, start + duration, resolution
                ).tolist()
            )
            new_event_groups.append([event])

    response = groups_to_dict(
        new_event_groups, value_groups, generic_asset_type_name="event"
    )
    response["start"] = isodate.datetime_isoformat(start)
    response["duration"] = isodate.duration_isoformat(duration)
    response["unit"] = unit

    d, s = request_processed()
    return dict(**response, **d), s


@usef_roles_accepted("Prosumer")  # noqa: C901
@type_accepted("PostUdiEventRequest")
@units_accepted("State of charge", "kWh", "MWh")
@as_json
def post_udi_event_response(unit):

    if not has_assets():
        current_app.logger.info("User doesn't seem to have any assets.")

    form = get_form_from_request(request)

    # check datetime, or use bvp_now
    if "datetime" not in form:
        return invalid_datetime("Missing datetime parameter.")
    else:
        datetime = parse_isodate_str(form.get("datetime"))
        if datetime is None:
            return invalid_datetime(
                "Cannot parse datetime string %s as iso date" % form.get("datetime")
            )
        if datetime.tzinfo is None:
            current_app.logger.warn(
                "Cannot parse timezone of 'datetime' value %s" % form.get("datetime")
            )
            return invalid_timezone()

    # parse event/address info
    if "event" not in form:
        return invalid_domain("No event identifier sent.")
    ea = validate_entity_address(form.get("event"), entity_type="event")
    if ea is None:
        current_app.logger.warn(
            "Cannot parse this event's entity address: %s." % form.get("event")
        )
        return invalid_domain("Cannot parse event.")

    asset_id = ea["asset_id"]
    event_id = ea["event_id"]
    event_type = ea["event_type"]

    if event_type != "soc":
        return unrecognized_event(event_id, event_type)

    # get asset
    asset: Asset = Asset.query.filter_by(id=asset_id).one_or_none()
    if asset is None or not can_access_asset(asset):
        current_app.logger.warn("Cannot identify asset via %s." % ea)
        return unrecognized_connection_group()
    if asset.asset_type_name != "battery":
        return invalid_domain("Asset ID:%s is not a battery." % asset_id)

    # check if last date is before this date
    if asset.soc_datetime is not None:
        if asset.soc_datetime >= datetime:
            msg = (
                "The date of the requested UDI event (%s) is earlier than the latest known date (%s)."
                % (datetime, asset.soc_datetime)
            )
            current_app.logger.warn(msg)
            return invalid_datetime(msg)

    # check if udi event id is higher than existing
    if asset.soc_udi_event_id is not None:
        if asset.soc_udi_event_id >= event_id:
            return outdated_event_id(event_id, asset.soc_udi_event_id)

    # get value
    if "value" not in form:
        return ptus_incomplete()
    value = form.get("value")
    if unit == "kWh":
        value = value / 1000.

    # store new soc in asset
    asset.soc_datetime = datetime
    asset.soc_udi_event_id = event_id
    asset.soc_in_mwh = value

    response = dict(type="PostUdiEventResponse")
    d, s = request_processed("Request has been processed.")
    return dict(**response, **d), s
