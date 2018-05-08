from flask import Flask, Blueprint
from flask_marshmallow import Marshmallow

# The api blueprint. It is registered with the Flask app (see app.py)
bvp_api = Blueprint('bvp_api', __name__)

ma: Marshmallow = None


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""
    global ma
    ma = Marshmallow(app)

    import bvp.api.endpoints  # this is necessary to load the endpoints
    app.register_blueprint(bvp_api)  # now registering the blueprint will affect all endpoints
