from flask import Flask, Blueprint, request, current_app
from flask_marshmallow import Marshmallow
from flask_security.views import login
from flask_json import as_json


# The api blueprint. It is registered with the Flask app (see app.py)
bvp_api = Blueprint('bvp_api', __name__)

ma: Marshmallow = None


@bvp_api.route('/api/request_auth_token', methods=["POST"])
@as_json
def request_auth_token():
    """Calling the login of flask security here, so we can
     * be exempt from csrf protection (this is a JSON-only endpoint)
     * use a more fitting name inside the api namespace
     * return the information in a nicer structure
    """
    csrf_enabled = current_app.config.get("WTF_CSRF_ENABLED", True)  # default is True, see Flask-WTF docs
    try:
        current_app.config["WTF_CSRF_ENABLED"] = False
        if not request.is_json:
            return {"errors": ["Content-type of request must be application/json"]}, 400
        login_response = login()  # this is doing the actual work
        return_code = login_response[1]
        if return_code != 200:
            return login_response[0].json['response'], return_code
        user_info = login_response[0].json['response']['user']
        return {"auth_token": user_info['authentication_token'], "user_id": user_info["id"]}
    except Exception as e:
        return {"errors": [str(e)]}
    finally:
        current_app.config["WTF_CSRF_ENABLED"] = csrf_enabled


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""
    global ma
    ma = Marshmallow(app)

    import bvp.api.endpoints  # this is necessary to load the endpoints

    app.register_blueprint(bvp_api)  # now registering the blueprint will affect all endpoints

    # # Load the following versions of the endpoints
    # from bvp.api.v1 import bvp_api as api_v1
    # from bvp.api.v1_1 import bvp_api as api_v1_1
    #
    # # Register the following blueprint versions to the api
    # app.register_blueprint(api_v1, url_prefix='/v1')
    # app.register_blueprint(api_v1_1, url_prefix='/v1.1')
