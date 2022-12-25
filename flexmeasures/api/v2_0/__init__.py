from flask import Flask, Blueprint

from flexmeasures.api.common.utils.deprecation_utils import deprecate_blueprint

flexmeasures_api = Blueprint("flexmeasures_api_v2_0", __name__)
deprecate_blueprint(
    flexmeasures_api,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html",
    sunset_date="2023-02-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html",
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.v2_0.routes  # noqa: F401 this is necessary to load the endpoints

    v2_0_api_prefix = "/api/v2_0"

    app.register_blueprint(flexmeasures_api, url_prefix=v2_0_api_prefix)
