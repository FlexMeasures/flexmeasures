from flask import Flask, Blueprint, request, current_app
from flask_marshmallow import Marshmallow
from flask_security.views import login, logout
from flask_json import as_json


# The api blueprint. It is registered with the Flask app (see app.py)
bvp_api = Blueprint("bvp_api", __name__)

ma: Marshmallow = None


@bvp_api.route("/requestAuthToken", methods=["POST"])
@as_json
def request_auth_token():
    """Calling the login of flask security here, so we can
     * be exempt from csrf protection (this is a JSON-only endpoint)
     * use a more fitting name inside the api namespace
     * return the information in a nicer structure
    """
    csrf_enabled = current_app.config.get(
        "WTF_CSRF_ENABLED", True
    )  # default is True, see Flask-WTF docs
    try:
        current_app.config["WTF_CSRF_ENABLED"] = False
        if not request.is_json:
            return {"errors": ["Content-type of request must be application/json"]}, 400
        from flask_login import current_user

        if current_user.is_authenticated:
            return {
                "auth_token": current_user.get_auth_token(),
                "user_id": current_user.id,
            }
        login_response = login()  # this logs in the user and also grabs the auth token.
        logout()  # make sure user is returned to the previous state of authentication
        if type(login_response) == tuple:
            return_code = login_response[1]
        else:
            return_code = login_response.status_code
        if return_code != 200:
            if type(login_response) == tuple:
                return login_response[0].json["response"], return_code
            else:
                return {"errors": ["We cannot log you in."]}, return_code
        user_info = login_response[0].json["response"]["user"]
        return {
            "auth_token": user_info["authentication_token"],
            "user_id": user_info["id"],
        }
    except Exception as e:
        return {"errors": [str(e)]}, 400
    finally:
        current_app.config["WTF_CSRF_ENABLED"] = csrf_enabled


@bvp_api.route('/', methods=['GET'])
@as_json
def get_versions() -> dict:
    """Public endpoint to list API versions"""
    response = {
        "message": "For these API versions a public endpoint is available listing its service. For example: "
                   "/api/v1/getService and /api/v1.1/getService. An authentication token can be requested at: "
                   "/api/requestAuthToken",
        "versions": ["v1", "v1.1"],
    }
    return response


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""
    global ma
    ma = Marshmallow(app)

    import bvp.api.endpoints  # this is necessary to load the endpoints

    app.register_blueprint(
        bvp_api, url_prefix='/api'
    )  # now registering the blueprint will affect all endpoints

    # Load the following versions of the endpoints
    from bvp.api.v1 import bvp_api as api_v1
    from bvp.api.v1_1 import bvp_api as api_v1_1

    # Register the following blueprint versions to the api
    app.register_blueprint(api_v1, url_prefix='/api/v1')
    app.register_blueprint(api_v1_1, url_prefix='/api/v1.1')
