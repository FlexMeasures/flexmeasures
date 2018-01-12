from flask import Blueprint
from werkzeug.exceptions import BadRequest, HTTPException, NotFound
from jinja2.exceptions import TemplateNotFound

from utils import render_a1vpp_template


# The views in this module can as blueprint be registered with the Flask app (see app.py)
a1_error_views = Blueprint('a1_error_views', __name__)


@a1_error_views.app_errorhandler(500)
def handle_error(e):
    print("Handling internal error")
    return render_a1vpp_template("error.html",
                                 error_class=e.__class__.__name__,
                                 error_description="We encountered an internal problem.",
                                 error_message=str(e)), 500


@a1_error_views.app_errorhandler(HTTPException)
def handle_http_exception(e):
    print("Handling http exception")
    return render_a1vpp_template("error.html",
                                 error_class=e.__class__.__name__,
                                 error_description="We encountered an Http exception.",
                                 error_message=str(e)), 400


@a1_error_views.app_errorhandler(BadRequest)
def handle_bad_request(e):
    print("Handling bad request")
    return render_a1vpp_template("error.html",
                                 error_class=e.__class__.__name__,
                                 error_description="We encountered a bad request.",
                                 error_message=str(e)), 400


@a1_error_views.app_errorhandler(TemplateNotFound)
@a1_error_views.app_errorhandler(NotFound)
def handle_not_found(e):
    print("Handling NotFound error")
    return render_a1vpp_template("error.html",
                                 error_class=e.__class__.__name__,
                                 error_description="The page you are looking for cannot be found.",
                                 error_message=str(e)), 404
