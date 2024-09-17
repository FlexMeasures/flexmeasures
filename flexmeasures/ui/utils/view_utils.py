"""Utilities for views"""

from __future__ import annotations

import json
import os
import subprocess

from flask import render_template, request, session, current_app
from flask_security.core import current_user

from flexmeasures.data import db
from flexmeasures import __version__ as flexmeasures_version
from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.ui.utils.breadcrumb_utils import get_breadcrumb_info
from flexmeasures.utils import time_utils
from flexmeasures.ui import flexmeasures_ui
from flexmeasures.data.models.user import User, Account
from flexmeasures.ui.utils.chart_defaults import chart_options
from flexmeasures.ui.utils.color_defaults import get_color_settings


def render_flexmeasures_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    variables["FLEXMEASURES_ENFORCE_SECURE_CONTENT_POLICY"] = current_app.config.get(
        "FLEXMEASURES_ENFORCE_SECURE_CONTENT_POLICY"
    )
    variables["documentation_exists"] = False
    if os.path.exists(
        "%s/static/documentation/html/index.html" % flexmeasures_ui.root_path
    ):
        variables["documentation_exists"] = True

    # use event_starts_after and event_ends_before from session if not given
    variables["event_starts_after"] = variables.get(
        "event_starts_after"
    ) or session.get("event_starts_after")
    variables["event_ends_before"] = variables.get("event_ends_before") or session.get(
        "event_ends_before"
    )

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

    # Chart options passed to vega-embed
    options = chart_options.copy()
    if "sensor_id" in variables:
        options["downloadFileName"] = f"sensor-{variables['sensor_id']}"
    elif "asset" in variables:
        asset = variables["asset"]
        options["downloadFileName"] = f"asset-{asset.id}-{asset.name}"
    variables["chart_options"] = json.dumps(options)

    account: Account | None = (
        current_user.account if current_user.is_authenticated else None
    )

    # check if user/consultant has logo_url set
    if account:
        variables["menu_logo"] = (
            account.logo_url
            or (account.consultancy_account and account.consultancy_account.logo_url)
            or current_app.config.get("FLEXMEASURES_MENU_LOGO_PATH")
        )
    else:
        variables["menu_logo"] = current_app.config.get("FLEXMEASURES_MENU_LOGO_PATH")

    variables["extra_css"] = current_app.config.get("FLEXMEASURES_EXTRA_CSS_PATH")

    if "asset" in variables:
        variables["breadcrumb_info"] = get_breadcrumb_info(asset)
    variables.update(get_color_settings(account))  # add color settings to variables

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


ICON_MAPPING = {
    # site structure
    "evse": "icon-charging_station",
    "charge point": "icon-charging_station",
    "project": "icon-calculator",
    "tariff": "icon-time",
    "renewables": "icon-wind",
    "site": "icon-empty-marker",
    "scenario": "icon-binoculars",
    # weather
    "irradiance": "wi wi-horizon-alt",
    "temperature": "wi wi-thermometer",
    "wind direction": "wi wi-wind-direction",
    "wind speed": "wi wi-strong-wind",
}


def asset_icon_name(asset_type_name: str) -> str:
    """Icon name for this asset type.

    This can be used for UI html templates made with Jinja.
    ui.__init__ makes this function available as the filter "asset_icon".

    For example:
        <i class={{ asset_type.name | asset_icon }}></i>
    becomes (for a battery):
        <i class="icon-battery"></i>
    """
    if asset_type_name:
        asset_type_name = asset_type_name.lower()
    return ICON_MAPPING.get(asset_type_name, f"icon-{asset_type_name}")


def username(user_id) -> str:
    user = db.session.get(User, user_id)
    if user is None:
        current_app.logger.warning(f"Could not find user with id {user_id}")
        return ""
    else:
        return user.username


def accountname(account_id) -> str:
    account = db.session.get(Account, account_id)
    if account is None:
        current_app.logger.warning(f"Could not find account with id {account_id}")
        return ""
    else:
        return account.name
