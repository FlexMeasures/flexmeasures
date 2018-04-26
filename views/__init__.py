"""This module hosts the views. This file registers blueprints and hosts some helpful functions"""

from flask import Blueprint


# We provide two blueprints under which views can be grouped. They are registered with the Flask app (see app.py)
bvp_views = Blueprint('a1_views', __name__, static_folder='static', template_folder='templates')
bvp_error_views = Blueprint('a1_error_views', __name__)

# Now views can register
from views.dashboard import dashboard_view
from views.portfolio import portfolio_view
from views.control import control_view
from views.analytics import analytics_view

from views.auth import account_view


@bvp_views.route('/docs')
def docs_view():
    """ Render the Sphinx documentation """
    # Todo: render the docs with this nicer url and include the app's navigation menu
    return
