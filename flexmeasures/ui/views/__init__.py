"""This module hosts the views. This file registers blueprints and hosts some helpful functions"""

from flexmeasures.ui import flexmeasures_ui

# Now views can register
from flexmeasures.ui.views.new_dashboard import dashboard_view  # noqa: F401
from flexmeasures.ui.views.control import control_view  # noqa: F401

from flexmeasures.ui.views.logged_in_user import (  # noqa: F401  # noqa: F401
    logged_in_user_view,
)


@flexmeasures_ui.route("/docs")
def docs_view():
    """Render the Sphinx documentation"""
    # Todo: render the docs with this nicer url and include the app's navigation menu
    return
