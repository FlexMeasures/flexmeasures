# flake8: noqa: C901
from datetime import timedelta

import inflect
import isodate
from flask_json import as_json
from flask import request, current_app
import numpy as np
import pandas as pd
from rq.job import Job, NoSuchJobError

from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.api.common.responses import (
    invalid_domain,
    invalid_datetime,
    invalid_timezone,
    request_processed,
    incomplete_event,
    unrecognized_event,
    unrecognized_event_type,
    unknown_schedule,
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
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.resources import has_assets, can_access_asset
from flexmeasures.data.services.scheduling import create_scheduling_job


p = inflect.engine()


@type_accepted("GetDeviceMessageRequest")
@assets_required("event")
@optional_duration_accepted(timedelta(hours=6))
@as_json
def get_device_message_response(generic_asset_name_groups, duration):

    unit = "MW"
    planning_horizon = min(
        duration, current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")
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
            if asset.asset_type_name not in ("battery", "one-way_evse", "two-way_evse"):
                return invalid_domain(
                    f"API version 1.3 only supports device messages for batteries and Electric Vehicle Supply Equipment (EVSE). "
                    f"Asset ID:{asset_id} is not a battery or EVSE, but {p.a(asset.asset_type.display_name)}."
                )

            # Use the event_id to look up the schedule start
            if event_type not in ("soc", "soc-with-targets"):
                return unrecognized_event_type(event_type)
            connection = current_app.queues["scheduling"].connection
            try:  # First try the scheduling queue
                job = Job.fetch(event, connection=connection)
            except NoSuchJobError:  # Then try the most recent event_id (stored as an asset attribute)
                if event_id == asset.soc_udi_event_id:
                    schedule_start = asset.soc_datetime
                    message = (
                        "Your UDI event is the most recent event for this device, but "
                    )
                else:
                    return unrecognized_event(event_id, event_type)
            else:
                if job.is_finished:
                    message = "A scheduling job has been processed based on your UDI event, but "
                elif job.is_failed:  # Try to inform the user on why the job failed
                    e = job.meta.get(
                        "exception",
                        Exception(
                            "The job does not state why it failed. "
                            "The worker may be missing an exception handler, "
                            "or its exception handler is not storing the exception as job meta data."
                        ),
                    )
                    return unknown_schedule(
                        f"Scheduling job failed with {type(e).__name__}: {e}"
                    )
                elif job.is_started:
                    return unknown_schedule("Scheduling job in progress.")
                elif job.is_queued:
                    return unknown_schedule("Scheduling job waiting to be processed.")
                elif job.is_deferred:
                    try:
                        preferred_job = job.dependency
                    except NoSuchJobError:
                        return unknown_schedule(
                            "Scheduling job waiting for unknown job to be processed."
                        )
                    return unknown_schedule(
                        f'Scheduling job waiting for {preferred_job.status} job "{preferred_job.id}" to be processed.'
                    )
                else:
                    return unknown_schedule("Scheduling job has an unknown status.")
                schedule_start = job.kwargs["start"]

            schedule_data_source_name = "Seita"
            scheduler_source = DataSource.query.filter_by(
                name="Seita", type="scheduling script"
            ).one_or_none()
            if scheduler_source is None:
                return unknown_schedule(
                    message + f'no data is known from "{schedule_data_source_name}".'
                )
            power_values = (
                Power.query.filter(Power.asset_id == asset.id)
                .filter(Power.data_source_id == scheduler_source.id)
                .filter(Power.datetime >= schedule_start)
                .filter(Power.datetime < schedule_start + planning_horizon)
                .all()
            )
            consumption_schedule = pd.Series(
                [-v.value for v in power_values],
                index=pd.DatetimeIndex([v.datetime for v in power_values]),
            )  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
            if consumption_schedule.empty:
                return unknown_schedule(
                    message + "the schedule was not found in the database."
                )

            # Update the planning window
            resolution = asset.event_resolution
            start = consumption_schedule.index[0]
            duration = min(
                duration, consumption_schedule.index[-1] + resolution - start
            )
            consumption_schedule = consumption_schedule[
                start : start + duration - resolution
            ]
            value_groups.append(consumption_schedule.tolist())
            new_event_groups.append(event)

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

    if event_type not in ("soc", "soc-with-targets"):
        return unrecognized_event_type(event_type)

    # get asset
    asset: Asset = Asset.query.filter_by(id=asset_id).one_or_none()
    if asset is None or not can_access_asset(asset):
        current_app.logger.warning("Cannot identify asset via %s." % ea)
        return unrecognized_connection_group()
    if asset.asset_type_name not in ("battery", "one-way_evse", "two-way_evse"):
        return invalid_domain(
            f"API version 1.3 only supports UDI events for batteries and Electric Vehicle Supply Equipment (EVSE). "
            f"Asset ID:{asset_id} is not a battery or EVSE, but {p.a(asset.asset_type.display_name)}."
        )

    # unless on play, keep events ordered by entry date and ID
    if current_app.config.get("FLEXMEASURES_MODE") != "play":
        # do not allow new date to precede previous date
        if asset.soc_datetime is not None:
            if datetime < asset.soc_datetime:
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
    try:
        value = float(form.get("value"))
    except ValueError:
        extra_info = "Request includes empty or ill-formatted value(s)."
        current_app.logger.warning(extra_info)
        return ptus_incomplete(extra_info)
    if unit == "kWh":
        value = value / 1000.0

    # set soc targets
    start_of_schedule = datetime
    end_of_schedule = datetime + current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")
    resolution = asset.event_resolution
    soc_targets = pd.Series(
        np.nan,
        index=pd.date_range(
            start_of_schedule, end_of_schedule, freq=resolution, closed="right"
        ),  # note that target values are indexed by their due date (i.e. closed="right")
    )

    if event_type == "soc-with-targets":
        if "targets" not in form:
            return incomplete_event(
                event_id,
                event_type,
                "Cannot process event %s with missing targets." % form.get("event"),
            )
        for target in form.get("targets"):

            # get target value
            if "value" not in target:
                return ptus_incomplete("Target missing value parameter.")
            try:
                target_value = float(target["value"])
            except ValueError:
                extra_info = "Request includes empty or ill-formatted target value(s)."
                current_app.logger.warning(extra_info)
                return ptus_incomplete(extra_info)
            if unit == "kWh":
                target_value = target_value / 1000.0

            # get target datetime
            if "datetime" not in target:
                return invalid_datetime("Target missing datetime parameter.")
            else:
                target_datetime = parse_isodate_str(target["datetime"])
                if target_datetime is None:
                    return invalid_datetime(
                        "Cannot parse target datetime string %s as iso date"
                        % target["datetime"]
                    )
                if target_datetime.tzinfo is None:
                    current_app.logger.warning(
                        "Cannot parse timezone of target 'datetime' value %s"
                        % target["datetime"]
                    )
                    return invalid_timezone(
                        "Target datetime should explicitly state a timezone."
                    )
                if target_datetime > end_of_schedule:
                    return invalid_datetime(
                        f'Target datetime exceeds {end_of_schedule}. Maximum scheduling horizon is {current_app.config.get("FLEXMEASURES_PLANNING_HORIZON")}.'
                    )
                target_datetime = target_datetime.astimezone(
                    soc_targets.index.tzinfo
                )  # otherwise DST would be problematic

            # set target
            soc_targets.loc[target_datetime] = target_value

    create_scheduling_job(
        asset.id,
        start_of_schedule,
        end_of_schedule,
        resolution=resolution,
        belief_time=datetime,
        soc_at_start=value,
        soc_targets=soc_targets,
        udi_event_ea=form.get("event"),
        enqueue=True,
    )

    # store new soc in asset
    asset.soc_datetime = datetime
    asset.soc_udi_event_id = event_id
    asset.soc_in_mwh = value

    db.session.commit()
    return request_processed()
