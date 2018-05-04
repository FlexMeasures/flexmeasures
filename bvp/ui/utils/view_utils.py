"""Utilities for views"""
import os
import subprocess
from typing import Tuple

from flask import render_template, session, current_app
from bokeh.resources import CDN
from flask_security.core import current_user

from bvp.utils import time_utils
from bvp.ui import bvp_ui


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
    variables["resolution_human"] = time_utils.freq_label_to_human_readable_label(session.get("resolution", ""))

    variables["git_version"], variables["git_commits_since"], variables["git_hash"] = get_git_description()
    app_start_time = current_app.config.get("START_TIME")
    variables["app_running_since"] = time_utils.naturalized_datetime(app_start_time)

    variables["user_is_logged_in"] = current_user.is_authenticated
    variables["user_is_admin"] = current_user.is_authenticated and current_user.has_role("admin")
    variables["user_email"] = current_user.is_authenticated and current_user.email or ""

    return render_template(html_filename, **variables)


def get_git_description() -> Tuple[str, int, str]:
    """ Return the latest git version (tag) as a string, the number of commits since then as an int and the
    current commit hash as string. """
    def _minimal_ext_cmd(cmd: list):
        # construct minimal environment
        env = {}
        for k in ['SYSTEMROOT', 'PATH']:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v
        # LANGUAGE is used on win32
        env['LANGUAGE'] = 'C'
        env['LANG'] = 'C'
        env['LC_ALL'] = 'C'
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env).communicate()[0]

    version = "Unknown"
    commits_since = 0
    sha = "Unknown"
    try:
        git_output = _minimal_ext_cmd(['git', 'describe', '--always', '--long'])
        components = git_output.strip().decode('ascii').split('-')
        sha = components.pop()
        commits_since = int(components.pop())
        version = "-".join(components)
    except OSError as ose:
        current_app.logger.warn("Problem when reading git describe: %s" % ose)

    return version, commits_since, sha
