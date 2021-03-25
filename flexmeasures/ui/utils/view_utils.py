"""Utilities for views"""
import os
import subprocess
from typing import Tuple, List, Optional
from datetime import datetime

from flask import render_template, request, session, current_app
from bokeh.resources import CDN
from flask_security.core import current_user
from werkzeug.exceptions import BadRequest
import iso8601
import pytz

from flexmeasures import __version__ as flexmeasures_version
from flexmeasures.utils import time_utils
from flexmeasures.ui import flexmeasures_ui
from flexmeasures.data.models.user import User
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.weather import WeatherSensorType
from flexmeasures.data.services.resources import Resource


def render_flexmeasures_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    variables["documentation_exists"] = False
    if os.path.exists(
        "%s/static/documentation/html/index.html" % flexmeasures_ui.root_path
    ):
        variables["documentation_exists"] = True

    variables["show_queues"] = False
    if current_user.is_authenticated:
        if (
            current_user.has_role("admin")
            or current_app.config.get("FLEXMEASURES_MODE", "") == "demo"
        ):
            variables["show_queues"] = True

    variables["start_time"] = time_utils.get_default_start_time()
    if "start_time" in session:
        variables["start_time"] = session["start_time"]

    variables["end_time"] = time_utils.get_default_end_time()
    if "end_time" in session:
        variables["end_time"] = session["end_time"]

    variables["page"] = html_filename.split("/")[-1].replace(".html", "")
    if "show_datepicker" not in variables:
        variables["show_datepicker"] = variables["page"] in ("analytics", "portfolio")

    variables["contains_plots"] = False
    if any([n.endswith(("plots_div", "plots_divs")) for n in variables.keys()]):
        variables["contains_plots"] = True
        variables["bokeh_css_resources"] = CDN.render_css()
        variables["bokeh_js_resources"] = CDN.render_js()

    variables["resolution"] = session.get("resolution", "")
    variables["resolution_human"] = time_utils.freq_label_to_human_readable_label(
        session.get("resolution", "")
    )
    variables["horizon_human"] = time_utils.freq_label_to_human_readable_label(
        session.get("forecast_horizon", "")
    )

    variables["flexmeasures_version"] = flexmeasures_version

    (
        variables["git_version"],
        variables["git_commits_since"],
        variables["git_hash"],
    ) = get_git_description()
    app_start_time = current_app.config.get("START_TIME")
    variables["app_running_since"] = time_utils.naturalized_datetime_str(app_start_time)

    variables["user_is_logged_in"] = current_user.is_authenticated
    variables[
        "user_is_admin"
    ] = current_user.is_authenticated and current_user.has_role("admin")
    variables[
        "user_is_anonymous"
    ] = current_user.is_authenticated and current_user.has_role("anonymous")
    variables["user_email"] = current_user.is_authenticated and current_user.email or ""
    variables["user_name"] = (
        current_user.is_authenticated and current_user.username or ""
    )

    return render_template(html_filename, **variables)


def clear_session():
    for skey in [
        k for k in session.keys() if k not in ("_id", "user_id", "csrf_token")
    ]:
        current_app.logger.info(
            "Removing %s:%s from session ... " % (skey, session[skey])
        )
        del session[skey]


def set_time_range_for_session():
    """Set period (start_date, end_date and resolution) on session if they are not yet set.
    Also set the forecast horizon, if given."""
    if "start_time" in request.values:
        session["start_time"] = time_utils.localized_datetime(
            iso8601.parse_date(request.values.get("start_time"))
        )
    elif "start_time" not in session:
        session["start_time"] = time_utils.get_default_start_time()
    else:
        if (
            session["start_time"].tzinfo is None
        ):  # session storage seems to lose tz info
            session["start_time"] = (
                session["start_time"]
                .replace(tzinfo=pytz.utc)
                .astimezone(time_utils.get_timezone())
            )

    if "end_time" in request.values:
        session["end_time"] = time_utils.localized_datetime(
            iso8601.parse_date(request.values.get("end_time"))
        )
    elif "end_time" not in session:
        session["end_time"] = time_utils.get_default_end_time()
    else:
        if session["end_time"].tzinfo is None:
            session["end_time"] = (
                session["end_time"]
                .replace(tzinfo=pytz.utc)
                .astimezone(time_utils.get_timezone())
            )

    # Our demo server works only with the current year's data
    if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
        session["start_time"] = session["start_time"].replace(year=datetime.now().year)
        session["end_time"] = session["end_time"].replace(year=datetime.now().year)
        if session["start_time"] >= session["end_time"]:
            session["start_time"], session["end_time"] = (
                session["end_time"],
                session["start_time"],
            )

    if session["start_time"] >= session["end_time"]:
        raise BadRequest(
            "Start time %s is not after end time %s."
            % (session["start_time"], session["end_time"])
        )

    session["resolution"] = time_utils.decide_resolution(
        session["start_time"], session["end_time"]
    )

    if "forecast_horizon" in request.values:
        session["forecast_horizon"] = request.values.get("forecast_horizon")
    allowed_horizons = time_utils.forecast_horizons_for(session["resolution"])
    if (
        session.get("forecast_horizon") not in allowed_horizons
        and len(allowed_horizons) > 0
    ):
        session["forecast_horizon"] = allowed_horizons[0]


def ensure_timing_vars_are_set(
    time_window: Tuple[Optional[datetime], Optional[datetime]],
    resolution: Optional[str],
) -> Tuple[Tuple[datetime, datetime], str]:
    """
    Ensure that time window and resolution variables are set,
    even if we don't have them available ― in that case,
    get them from the session.
    """
    start = time_window[0]
    end = time_window[-1]
    if None in (start, end, resolution):
        current_app.logger.warning("Setting time range for session.")
        set_time_range_for_session()
        start_out: datetime = session["start_time"]
        end_out: datetime = session["end_time"]
        resolution_out: str = session["resolution"]
    else:
        start_out = start  # type: ignore
        end_out = end  # type: ignore
        resolution_out = resolution  # type: ignore

    return (start_out, end_out), resolution_out


def set_session_market(resource: Resource) -> Market:
    """Set session["market"] to something, based on the available markets or the request.
    Returns the selected market, or None."""
    market = resource.assets[0].market
    if market is not None:
        session["market"] = market.name
    elif "market" not in session:
        session["market"] = None
    if (
        "market" in request.args
    ):  # [GET] Set by user clicking on a link somewhere (e.g. dashboard)
        session["market"] = request.args["market"]
    if (
        "market" in request.form
    ):  # [POST] Set by user in drop-down field. This overwrites GET, as the URL remains.
        session["market"] = request.form["market"]
    return Market.query.filter(Market.name == session["market"]).one_or_none()


def set_session_sensor_type(
    accepted_sensor_types: List[WeatherSensorType],
) -> WeatherSensorType:
    """Set session["sensor_type"] to something, based on the available sensor types or the request.
    Returns the selected sensor type, or None."""

    sensor_type_name = ""
    if "sensor_type" in session:
        sensor_type_name = session["sensor_type"]
    if (
        "sensor_type" in request.args
    ):  # [GET] Set by user clicking on a link somewhere (e.g. dashboard)
        sensor_type_name = request.args["sensor_type"]
    if (
        "sensor_type" in request.form
    ):  # [POST] Set by user in drop-down field. This overwrites GET, as the URL remains.
        sensor_type_name = request.form["sensor_type"]
    requested_sensor_type = WeatherSensorType.query.filter(
        WeatherSensorType.name == sensor_type_name
    ).one_or_none()
    if (
        requested_sensor_type not in accepted_sensor_types
        and len(accepted_sensor_types) > 0
    ):
        sensor_type = accepted_sensor_types[0]
        session["sensor_type"] = sensor_type.name
        return sensor_type
    elif len(accepted_sensor_types) == 0:
        session["sensor_type"] = None
    else:
        session["sensor_type"] = requested_sensor_type.name
        return requested_sensor_type


def set_session_resource(
    assets: List[Asset], groups_with_assets: List[str]
) -> Optional[Resource]:
    """
    Set session["resource"] to something, based on the available asset groups or the request.

    Returns the selected resource instance, or None.
    """
    if (
        "resource" in request.args
    ):  # [GET] Set by user clicking on a link somewhere (e.g. dashboard)
        session["resource"] = request.args["resource"]
    if (
        "resource" in request.form
    ):  # [POST] Set by user in drop-down field. This overwrites GET, as the URL remains.
        session["resource"] = request.form["resource"]

    if "resource" not in session:  # set some default, if possible
        if len(groups_with_assets) > 0:
            session["resource"] = groups_with_assets[0]
        elif len(assets) > 0:
            session["resource"] = assets[0].name
        else:
            return None

    return Resource(session["resource"])


def set_individual_traces_for_session():
    """
    Set session["showing_individual_traces_for"] to a value ("none", "power", "schedules").
    """
    var_name = "showing_individual_traces_for"
    if var_name not in session:
        session[var_name] = "none"  # default setting: we show traces aggregated
    if var_name in request.values and request.values[var_name] in (
        "none",
        "power",
        "schedules",
    ):
        session[var_name] = request.values[var_name]


def get_git_description() -> Tuple[str, int, str]:
    """
    Get information about the SCM (git) state if possible (if a .git directory exists).

    Returns the latest git version (tag) as a string, the number of commits since then as an int and the
    current commit hash as string.
    """

    def _minimal_ext_cmd(cmd: list):
        # construct minimal environment
        env = {}
        for k in ["SYSTEMROOT", "PATH"]:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v
        # LANGUAGE is used on win32
        env["LANGUAGE"] = "C"
        env["LANG"] = "C"
        env["LC_ALL"] = "C"
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env).communicate()[0]

    version = "Unknown"
    commits_since = 0
    sha = "Unknown"

    path_to_flexmeasures_root = os.path.join(
        os.path.dirname(__file__), "..", "..", ".."
    )
    if os.path.exists(os.path.join(path_to_flexmeasures_root, ".git")):
        commands = ["git", "describe", "--always", "--long"]
        try:
            git_output = _minimal_ext_cmd(commands)
            components = git_output.strip().decode("ascii").split("-")
            if not (len(components) == 1 and components[0] == ""):
                sha = components.pop()
                if len(components) > 0:
                    commits_since = int(components.pop())
                    version = "-".join(components)
        except OSError as ose:
            current_app.logger.warning("Problem when reading git describe: %s" % ose)

    return version, commits_since, sha


def asset_icon_name(asset_type_name: str) -> str:
    """Icon name for this asset type.

    This can be used for UI html templates made with Jinja.
    ui.__init__ makes this function available as the filter "asset_icon".

    For example:
        <i class={{ asset_type.name | asset_icon }}></i>
    becomes (for a battery):
        <i class="icon-battery"></i>
    """
    # power asset exceptions
    if "evse" in asset_type_name.lower():
        return "icon-charging_station"
    # weather exceptions
    if asset_type_name == "radiation":
        return "wi wi-horizon-alt"
    elif asset_type_name == "temperature":
        return "wi wi-thermometer"
    elif asset_type_name == "wind_direction":
        return "wi wi-wind-direction"
    elif asset_type_name == "wind_speed":
        return "wi wi-strong-wind"
    # aggregation exceptions
    elif asset_type_name == "renewables":
        return "icon-wind"
    return f"icon-{asset_type_name}"


def username(user_id) -> str:
    user = User.query.get(user_id)
    if user is None:
        current_app.logger.warning(f"Could not find user with id {user_id}")
        return ""
    else:
        return user.username
