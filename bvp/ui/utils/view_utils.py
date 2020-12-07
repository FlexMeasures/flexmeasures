"""Utilities for views"""
import os
import subprocess
from typing import Tuple, List

from flask import render_template, request, session, current_app
from bokeh.resources import CDN
from flask_security.core import current_user

from bvp.utils import time_utils
from bvp.ui import bvp_ui
from bvp.data.models.user import User
from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensorType
from bvp.data.services.resources import Resource


def render_bvp_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    variables["documentation_exists"] = False
    if os.path.exists("%s/static/documentation/html/index.html" % bvp_ui.root_path):
        variables["documentation_exists"] = True

    variables["show_queues"] = False
    if current_user.is_authenticated:
        if (
            current_user.has_role("admin")
            or current_app.config.get("BVP_MODE", "") == "demo"
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
) -> Resource:
    """Set session["resource"] to something, based on the available asset groups or the request.
    Returns the selected resource, or None."""
    if "resource" not in session:  # set some default, if possible
        if len(groups_with_assets) > 0:
            session["resource"] = groups_with_assets[0]
        elif len(assets) > 0:
            session["resource"] = assets[0].name
    if (
        "resource" in request.args
    ):  # [GET] Set by user clicking on a link somewhere (e.g. dashboard)
        session["resource"] = request.args["resource"]
    if (
        "resource" in request.form
    ):  # [POST] Set by user in drop-down field. This overwrites GET, as the URL remains.
        session["resource"] = request.form["resource"]
    return Resource(session["resource"])


def get_git_description() -> Tuple[str, int, str]:
    """Return the latest git version (tag) as a string, the number of commits since then as an int and the
    current commit hash as string."""

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
    try:
        commands = ["git", "describe", "--always", "--long"]
        path_to_bvp = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        if not os.path.exists(os.path.join(path_to_bvp, ".git")):
            # convention if we are operating in a non-git checkout, could be made configurable
            commands.insert(
                1, "--git-dir=%s" % os.path.join(path_to_bvp, "..", "bvp.git")
            )
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
