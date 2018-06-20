from flask import Blueprint

# The api blueprint. It is registered with the Flask app (see app.py)
bvp_api = Blueprint("bvp_api_v1_1", __name__)

import bvp.api.v1_1.routes  # this is necessary to load the endpoints

