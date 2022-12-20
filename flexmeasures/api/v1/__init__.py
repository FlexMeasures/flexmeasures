from flask import Flask, Blueprint

from flexmeasures.api.common.utils.deprecation_utils import deprecate_blueprint


# The api blueprint. It is registered with the Flask app (see register_at)
flexmeasures_api = Blueprint("flexmeasures_api_v1", __name__)
deprecate_blueprint(
    flexmeasures_api,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
    sunset_date="2023-02-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/latest/api/v1.html",
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.v1.routes  # noqa: F401 this is necessary to load the endpoints

    app.register_blueprint(flexmeasures_api, url_prefix="/api/v1")
