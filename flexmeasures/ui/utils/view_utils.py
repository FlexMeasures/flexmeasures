"""Utilities for views"""
from __future__ import annotations

import json
import os
import subprocess

from flask import render_template, request, session, current_app
from flask_security.core import current_user

from flexmeasures import __version__ as flexmeasures_version
from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.utils import time_utils
from flexmeasures.ui import flexmeasures_ui
from flexmeasures.data.models.user import User, Account
from flexmeasures.ui.utils.chart_defaults import chart_options


def render_flexmeasures_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    variables["flask_env"] = current_app.env
    variables["documentation_exists"] = False
    if os.path.exists(
        "%s/static/documentation/html/index.html" % flexmeasures_ui.root_path
    ):
        variables["documentation_exists"] = True

    variables["show_queues"] = False
    if current_user.is_authenticated:
        if (
            user_has_admin_access(current_user, "update")
            or current_app.config.get("FLEXMEASURES_MODE", "") == "demo"
        ):
            variables["show_queues"] = True

    variables["event_starts_after"] = session.get("event_starts_after")
    variables["event_ends_before"] = session.get("event_ends_before")
    variables["chart_type"] = session.get("chart_type", "bar_chart")

    variables["page"] = html_filename.split("/")[-1].replace(".html", "")

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
    variables["loaded_plugins"] = ", ".join(
        f"{p_name} (v{p_version})"
        for p_name, p_version in current_app.config.get("LOADED_PLUGINS", {}).items()
    )

    variables["user_is_logged_in"] = current_user.is_authenticated
    variables["user_is_admin"] = user_has_admin_access(current_user, "update")
    variables["user_has_admin_reader_rights"] = user_has_admin_access(
        current_user, "read"
    )
    variables[
        "user_is_anonymous"
    ] = current_user.is_authenticated and current_user.has_role("anonymous")
    variables["user_email"] = current_user.is_authenticated and current_user.email or ""
    variables["user_name"] = (
        current_user.is_authenticated and current_user.username or ""
    )
    variables["js_versions"] = current_app.config.get("FLEXMEASURES_JS_VERSIONS")
    variables["chart_options"] = json.dumps(chart_options)

    variables["menu_logo"] = current_app.config.get("FLEXMEASURES_MENU_LOGO_PATH")
    variables["extra_css"] = current_app.config.get("FLEXMEASURES_EXTRA_CSS_PATH")

    return render_template(html_filename, **variables)


def clear_session():
    for skey in [
        k
        for k in session.keys()
        if k not in ("_fresh", "_id", "_user_id", "csrf_token", "fs_cc", "fs_paa")
    ]:
        current_app.logger.info(
            "Removing %s:%s from session ... " % (skey, session[skey])
        )
        del session[skey]


def set_session_variables(*var_names: str):
    """Store request values as session variables, for a consistent UX across UI page loads.

    >>> set_session_variables("event_starts_after", "event_ends_before", "chart_type")
    """
    for var_name in var_names:
        var = request.values.get(var_name)
        if var is not None:
            session[var_name] = var


def get_git_description() -> tuple[str, int, str]:
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
    if asset_type_name == "irradiance":
        return "wi wi-horizon-alt"
    elif asset_type_name == "temperature":
        return "wi wi-thermometer"
    elif asset_type_name == "wind direction":
        return "wi wi-wind-direction"
    elif asset_type_name == "wind speed":
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


def accountname(account_id) -> str:
    account = Account.query.get(account_id)
    if account is None:
        current_app.logger.warning(f"Could not find account with id {account_id}")
        return ""
    else:
        return account.name
