"""Utilities for views"""
import os
import subprocess
from typing import Tuple, List
from urllib.parse import urlparse

from flask import render_template, request, session, current_app
from bokeh.resources import CDN
from flask_security.core import current_user

from bvp.utils import time_utils
from bvp.ui import bvp_ui
from bvp.data.models.assets import Asset


def render_bvp_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    variables["documentation_exists"] = False
    if os.path.exists("%s/static/documentation/html/index.html" % bvp_ui.root_path):
        variables["documentation_exists"] = True

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
    if any([n.endswith("plots_div") for n in variables.keys()]):
        variables["contains_plots"] = True
        variables["bokeh_css_resources"] = CDN.render_css()
        variables["bokeh_js_resources"] = CDN.render_js()

    variables["resolution"] = session.get("resolution", "")
    variables["resolution_human"] = time_utils.freq_label_to_human_readable_label(
        session.get("resolution", "")
    )

    variables["git_version"], variables["git_commits_since"], variables[
        "git_hash"
    ] = get_git_description()
    app_start_time = current_app.config.get("START_TIME")
    variables["app_running_since"] = time_utils.naturalized_datetime(app_start_time)

    variables["user_is_logged_in"] = current_user.is_authenticated
    variables[
        "user_is_admin"
    ] = current_user.is_authenticated and current_user.has_role("admin")
    variables["user_email"] = current_user.is_authenticated and current_user.email or ""

    return render_template(html_filename, **variables)


def set_session_resource(assets: List[Asset], groups_with_assets: List[str]):
    """Set session["resource"] to something, based on the available asset groups or the request."""
    if "resource" not in session:  # set some default, if possible
        if "solar" in groups_with_assets:
            session["resource"] = "solar"
        elif "wind" in groups_with_assets:
            session["resource"] = "wind"
        elif "vehicles" in groups_with_assets:
            session["resource"] = "vehicles"
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


def get_git_description() -> Tuple[str, int, str]:
    """ Return the latest git version (tag) as a string, the number of commits since then as an int and the
    current commit hash as string. """

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
            commits_since = int(components.pop())
            version = "-".join(components)
    except OSError as ose:
        current_app.logger.warn("Problem when reading git describe: %s" % ose)

    return version, commits_since, sha


def get_naming_authority() -> str:
    domain_name = urlparse(request.url).netloc
    reverse_domain_name = ".".join(domain_name.split('.')[::-1])
    return "2018-06.%s" % reverse_domain_name


def get_addressing_scheme() -> str:
    return "ea1"
