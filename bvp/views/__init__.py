"""This module hosts the views. This file registers blueprints and hosts some helpful functions"""

from flask import Blueprint


# We provide two blueprints under which views can be grouped. They are registered with the Flask app (see app.py)
bvp_ui = Blueprint('bvp_ui', __name__, static_folder='static', template_folder='templates')

# Now views can register
from bvp.views.dashboard import dashboard_view
from bvp.views.portfolio import portfolio_view
from bvp.views.control import control_view
from bvp.views.analytics import analytics_view

from bvp.views.auth import account_view


@bvp_ui.route('/docs')
def docs_view():
    """ Render the Sphinx documentation """
    # Todo: render the docs with this nicer url and include the app's navigation menu
    return
