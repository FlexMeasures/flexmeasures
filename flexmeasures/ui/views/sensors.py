from datetime import timedelta

from flask import current_app, request
from flask_classful import FlaskView, route
from flask_security import login_required
from markupsafe import Markup
from werkzeug.exceptions import NotFound
from webargs.flaskparser import use_kwargs

from flexmeasures.data import db
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.services.automations import (
    describe_cronstr,
    get_automations_feeding_sensor,
)
from flexmeasures.data.services.timerange import get_timerange
from flexmeasures.data.services.sensors import flex_config_fields_left_without_sensor
from flexmeasures import Sensor
from flexmeasures.ui.utils.auth_utils import (
    user_can_access,
    user_can_delete,
    user_can_read,
    user_can_update,
)
from flexmeasures.ui.utils.breadcrumb_utils import get_breadcrumb_info
from flexmeasures.ui.views.assets.utils import editor_paths_and_url
from flexmeasures.ui.utils.view_utils import (
    render_flexmeasures_template,
    available_units,
)
from flexmeasures.ui.views import (
    ATTRIBUTES_FIELD_LABEL,
    ATTRIBUTES_FIELD_DESCRIPTION,
)
from flexmeasures.auth.policy import check_access

# How many assets' flex-configs the sensor page names when deleting a sensor leaves fields without one.
MAX_NAMED_FIELD_GROUPS = 10


def describe_fields_left_without_sensor(sensor: Sensor) -> tuple[str, Markup]:
    """What the sensor page tells the user who deletes this sensor about the flex-config fields it would leave without a sensor.

    Before deleting, the confirmation names them, as plain text.
    After deleting, a toast links to the editor for each of them, which the page shows once it has moved on to the sensor's asset.
    A sensor can be referenced from assets the user cannot read, such as when it is public,
    so those are only counted, not named.
    A shared sensor, such as a price, can be referenced by many assets, so only the first few are named.

    :returns: The note for the confirmation, and the toast, each empty if deleting the sensor leaves no field without one.
    """
    lines = []
    links = []
    unreadable_assets = set()
    for asset, config_name, paths in flex_config_fields_left_without_sensor(sensor.id):
        if not user_can_read(asset):
            unreadable_assets.add(asset.id)
            continue
        paths, url = editor_paths_and_url(asset, config_name, paths)
        fields = ", ".join(paths)
        lines.append(f"- {asset.name}, {config_name}: {fields}")
        if asset.id == sensor.generic_asset_id:
            # The page moves on to this asset, whose own toast already links to these fields.
            continue
        links.append(
            Markup('<a href="{url}">{asset}</a> ({config}: {fields})').format(
                url=url, asset=asset.name, config=config_name, fields=fields
            )
        )
    if len(lines) > MAX_NAMED_FIELD_GROUPS:
        lines = lines[:MAX_NAMED_FIELD_GROUPS] + [
            f"- and {len(lines) - MAX_NAMED_FIELD_GROUPS} more"
        ]
    if len(links) > MAX_NAMED_FIELD_GROUPS:
        links = links[:MAX_NAMED_FIELD_GROUPS] + [
            Markup("and {count} more").format(count=len(links) - MAX_NAMED_FIELD_GROUPS)
        ]
    if unreadable_assets:
        unreadable = (
            "1 asset"
            if len(unreadable_assets) == 1
            else f"{len(unreadable_assets)} assets"
        )
        lines.append(f"- fields on {unreadable} you cannot see")
        links.append(
            Markup("fields on {assets} you cannot see").format(assets=unreadable)
        )
    if not lines:
        return "", Markup("")
    confirm_note = "\n".join(
        [
            "These flex-config fields refer to this sensor. They keep their default, bounds and source filters, but will need a new sensor:",
            *lines,
        ]
    )
    if not links:
        return confirm_note, Markup("")
    toast = Markup(
        "These flex-config fields referred to the deleted sensor, and need a new sensor: {fields}. Until then, scheduling uses the default of such a field as a fixed value, or ignores the field."
    ).format(fields=Markup("; ").join(links))
    return confirm_note, toast


class SensorUI(FlaskView):
    """
    This view creates several new UI endpoints for viewing sensors.

    todo: consider extending this view for crud purposes
    """

    route_base = "/sensors"
    trailing_slash = False

    @use_kwargs(StartEndTimeSchema, location="query")
    @login_required
    def get(self, id: int, **kwargs):
        """GET from /sensors/<id>
        The following query parameters are supported (should be used only together):
         - start_time: minimum time of the events to be shown
         - end_time: maximum time of the events to be shown

        In addition, the source query parameter can be used to pre-select a data source
        in the statistics panel (e.g. when linking here from an automation).
        """
        sensor = db.session.get(Sensor, id)
        if sensor is None:
            raise NotFound
        check_access(sensor, "read")
        can_create_children = user_can_access(sensor, "post-data")
        can_trigger_forecasts = user_can_access(sensor, "trigger-forecasts")
        has_enough_data = False
        planning_horizon: timedelta = current_app.config.get(
            "FLEXMEASURES_PLANNING_HORIZON", timedelta(days=2)
        )
        forecast_default_duration_days = max(
            1, min(7, int(planning_horizon.total_seconds() / 86400))
        )
        if can_trigger_forecasts:
            earliest, latest = get_timerange([sensor.id])
            has_enough_data = (latest - earliest) >= timedelta(days=2)
        return render_flexmeasures_template(
            "sensors/index.html",
            sensor=sensor,
            user_can_update_sensor=user_can_update(sensor),
            user_can_delete_sensor=user_can_delete(sensor),
            user_can_delete_sensor_data=user_can_access(sensor, "delete-data"),
            user_can_create_children_sensor=can_create_children,
            user_can_trigger_forecasts=can_trigger_forecasts,
            sensor_has_enough_data_for_forecast=has_enough_data,
            forecast_default_duration_days=forecast_default_duration_days,
            available_units=available_units(),
            msg="",
            breadcrumb_info=get_breadcrumb_info(sensor),
            event_starts_after=request.args.get("start_time"),
            event_ends_before=request.args.get("end_time"),
            attributes_label=ATTRIBUTES_FIELD_LABEL,
            attributes_description=ATTRIBUTES_FIELD_DESCRIPTION,
            preselected_source_id=request.args.get("source"),
            feeding_automations=[
                dict(
                    id=automation.id,
                    name=automation.name,
                    asset_id=automation.asset_id,
                    active=automation.active,
                    recurrence_description=describe_cronstr(automation.cronstr),
                )
                for automation in get_automations_feeding_sensor(sensor)
                if user_can_read(automation)
            ],
        )

    @login_required
    @route("/<id>/deletion-notes")
    def deletion_notes(self, id: int):
        """GET from /sensors/<id>/deletion-notes

        What to tell the user about deleting this sensor, fetched once they click to delete it,
        as finding the flex-config fields it would leave without a sensor means searching every asset.
        This is for the sensor page only, so its response may change, unlike that of the API.
        """
        sensor = db.session.get(Sensor, id)
        if sensor is None:
            raise NotFound
        check_access(sensor, "delete")
        confirmation_note, toast = describe_fields_left_without_sensor(sensor)
        return {"confirmation-note": confirmation_note, "toast": str(toast)}
