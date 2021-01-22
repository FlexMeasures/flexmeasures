from datetime import timedelta

import isodate
from flask_json import as_json
from flask import request, current_app

from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_datetime,
    invalid_timezone,
    request_processed,
    unrecognized_event,
    invalid_market,
    unknown_prices,
    unrecognized_connection_group,
    outdated_event_id,
    ptus_incomplete,
)
from flexmeasures.api.common.utils.api_utils import (
    groups_to_dict,
    get_form_from_request,
)
from flexmeasures.api.common.utils.validators import (
    type_accepted,
    assets_required,
    optional_duration_accepted,
    usef_roles_accepted,
    units_accepted,
    parse_isodate_str,
)
from flexmeasures.data.config import db
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.planning.battery import schedule_battery
from flexmeasures.data.models.planning.exceptions import UnknownPricesException
from flexmeasures.data.services.resources import has_assets, can_access_asset


@type_accepted("GetDeviceMessageRequest")
@assets_required("event")
@optional_duration_accepted(timedelta(hours=6))
@as_json
def get_device_message_response(generic_asset_name_groups, duration):

    unit = "MW"
    min_planning_horizon = timedelta(
        hours=24
    )  # user can request a shorter planning, but the scheduler takes into account at least this horizon
    planning_horizon = min(
        max(min_planning_horizon, duration),
        current_app.config.get("FLEXMEASURES_PLANNING_HORIZON"),
    )

    if not has_assets():
        current_app.logger.info("User doesn't seem to have any assets.")

    value_groups = []
    new_event_groups = []
    for event_group in generic_asset_name_groups:
        for event in event_group:

            # Parse the entity address
            try:
                ea = parse_entity_address(event, entity_type="event")
            except EntityAddressException as eae:
                return invalid_domain(str(eae))
            asset_id = ea["asset_id"]
            event_id = ea["event_id"]
            event_type = ea["event_type"]

            # Look for the Asset object
            asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
            if asset is None or not can_access_asset(asset):
                current_app.logger.warning(
                    "Cannot identify asset %s given the event." % event
                )
                return unrecognized_connection_group()
            if asset.asset_type_name != "battery":
                return invalid_domain(
                    "API version 1.2 only supports device messages for batteries. Asset ID:%s is not a battery."
                    % asset_id
                )
            if event_type != "soc" or event_id != asset.soc_udi_event_id:
                return unrecognized_event(event_id, event_type)
            start = asset.soc_datetime
            resolution = asset.event_resolution

            # Look for the Market object
            market = asset.market
            if market is None:
                return invalid_market()

            # Schedule the asset
            try:
                schedule = schedule_battery(
                    asset,
                    market,
                    start,
                    start + planning_horizon,
                    resolution,
                    soc_at_start=asset.soc_in_mwh,
                    prefer_charging_sooner=False,
                )
            except UnknownPricesException:
                return unknown_prices()
            else:
                # Update the planning window
                start = schedule.index[0]
                duration = min(duration, schedule.index[-1] + resolution - start)
                schedule = schedule[start : start + duration - resolution]
            value_groups.append(schedule.tolist())
            new_event_groups.append(event)

    response = groups_to_dict(
        new_event_groups, value_groups, generic_asset_type_name="event"
    )
    response["start"] = isodate.datetime_isoformat(start)
    response["duration"] = isodate.duration_isoformat(duration)
    response["unit"] = unit

    d, s = request_processed()
    return dict(**response, **d), s


@usef_roles_accepted("Prosumer")
@type_accepted("PostUdiEventRequest")
@units_accepted("State of charge", "kWh", "MWh")
@as_json
def post_udi_event_response(unit):  # noqa: C901

    if not has_assets():
        current_app.logger.info("User doesn't seem to have any assets.")

    form = get_form_from_request(request)

    # check datetime, or use server_now
    if "datetime" not in form:
        return invalid_datetime("Missing datetime parameter.")
    else:
        datetime = parse_isodate_str(form.get("datetime"))
        if datetime is None:
            return invalid_datetime(
                "Cannot parse datetime string %s as iso date" % form.get("datetime")
            )
        if datetime.tzinfo is None:
            current_app.logger.warning(
                "Cannot parse timezone of 'datetime' value %s" % form.get("datetime")
            )
            return invalid_timezone("Datetime should explicitly state a timezone.")

    # parse event/address info
    if "event" not in form:
        return invalid_domain("No event identifier sent.")
    try:
        ea = parse_entity_address(form.get("event"), entity_type="event")
    except EntityAddressException as eae:
        return invalid_domain(str(eae))

    asset_id = ea["asset_id"]
    event_id = ea["event_id"]
    event_type = ea["event_type"]

    if event_type != "soc":
        return unrecognized_event(event_id, event_type)

    # get asset
    asset: Asset = Asset.query.filter_by(id=asset_id).one_or_none()
    if asset is None or not can_access_asset(asset):
        current_app.logger.warning("Cannot identify asset via %s." % ea)
        return unrecognized_connection_group()
    if asset.asset_type_name != "battery":
        return invalid_domain(
            "API version 1.2 only supports UDI events for batteries. Asset ID:%s is not a battery."
            % asset_id
        )

    # unless on play, keep events ordered by entry date and ID
    if current_app.config.get("FLEXMEASURES_MODE") != "play":
        # do not allow new date to be after last date
        if asset.soc_datetime is not None:
            if asset.soc_datetime >= datetime:
                msg = (
                    "The date of the requested UDI event (%s) is earlier than the latest known date (%s)."
                    % (datetime, asset.soc_datetime)
                )
                current_app.logger.warning(msg)
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
        value = value / 1000.0

    # store new soc in asset
    asset.soc_datetime = datetime
    asset.soc_udi_event_id = event_id
    asset.soc_in_mwh = value

    db.session.commit()
    return request_processed("Request has been processed.")
