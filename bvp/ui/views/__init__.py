"""This module hosts the views. This file registers blueprints and hosts some helpful functions"""

from bvp.ui import bvp_ui

# Now views can register
from bvp.ui.views.dashboard import dashboard_view
from bvp.ui.views.portfolio import portfolio_view
from bvp.ui.views.control import control_view
from bvp.ui.views.analytics import analytics_view

from bvp.ui.views.auth import account_view


@bvp_ui.route("/docs")
def docs_view():
    """ Render the Sphinx documentation """
    # Todo: render the docs with this nicer url and include the app's navigation menu
    return
