"""UI-internal suggestions for the manual asset scheduling dialog."""

from flask import abort
from flask_classful import FlaskView, route
from flask_security import login_required
from webargs.flaskparser import use_kwargs

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.ui.views.assets.scheduling import schedule_options


class ScheduleOptionsSchema(StartEndTimeSchema):
    start_time = AwareDateTimeField(data_key="start-time", required=False)
    end_time = AwareDateTimeField(data_key="end-time", required=False)


def kebab_keys(value):
    """Keep UI-internal JSON fields consistent with newer API field names."""
    if isinstance(value, dict):
        return {key.replace("_", "-"): kebab_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [kebab_keys(item) for item in value]
    return value


class AssetSchedulingAPI(FlaskView):
    """Return lazy scheduling suggestions to FlexMeasures' own UI."""

    route_base = "/assets"
    trailing_slash = False

    @login_required
    @route("/<id>/schedule-options")
    @use_kwargs(ScheduleOptionsSchema, location="query")
    def schedule_options(self, id: str, start_time=None, end_time=None):
        asset = db.session.get(GenericAsset, int(id)) if id.isdigit() else None
        if asset is None:
            abort(404)
        check_access(asset, "read")
        check_access(asset, "trigger-schedules")
        if start_time is None or end_time is None:
            return {"message": "Provide start-time and end-time."}, 422
        return kebab_keys(schedule_options(asset, start_time, end_time))
