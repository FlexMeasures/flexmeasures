"""This module hosts the views. This file registers blueprints and hosts some helpful functions"""

from flexmeasures.ui import flexmeasures_ui

# Now views can register
from flexmeasures.ui.views.dashboard import dashboard_view  # noqa: F401
from flexmeasures.ui.views.portfolio import portfolio_view  # noqa: F401
from flexmeasures.ui.views.control import control_view  # noqa: F401
from flexmeasures.ui.views.analytics import analytics_view  # noqa: F401
from flexmeasures.ui.views.state import state_view  # noqa: F401

from flexmeasures.ui.views.account import account_view  # noqa: F401  # noqa: F401

from flexmeasures.ui.views.charts import get_power_chart  # noqa: F401


@flexmeasures_ui.route("/docs")
def docs_view():
    """ Render the Sphinx documentation """
    # Todo: render the docs with this nicer url and include the app's navigation menu
    return
