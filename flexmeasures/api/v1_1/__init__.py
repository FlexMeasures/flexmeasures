from flask import Flask, Blueprint

from flexmeasures.api.common.utils.deprecation_utils import deprecate_blueprint

# The api blueprint. It is registered with the Flask app (see app.py)
flexmeasures_api = Blueprint("flexmeasures_api_v1_1", __name__)
deprecate_blueprint(
    flexmeasures_api,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/v1_1.html",
    sunset_date="2023-02-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/latest/api/v1_1.html",
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.v1_1.routes  # noqa: F401 this is necessary to load the endpoints

    app.register_blueprint(flexmeasures_api, url_prefix="/api/v1_1")
