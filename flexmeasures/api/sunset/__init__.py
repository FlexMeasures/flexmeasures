"""
A place to keep all routes to endpoints that previously existed and are now sunset.
"""

from flask import Flask, Blueprint

from flexmeasures.api.common.utils.deprecation_utils import (
    deprecate_blueprint,
    sunset_blueprint,
)


# The sunset API blueprints. They are registered with the Flask app (see register_at)
flexmeasures_api_v1 = Blueprint("flexmeasures_api_v1", __name__)
flexmeasures_api_v1_1 = Blueprint("flexmeasures_api_v1_1", __name__)
flexmeasures_api_v1_2 = Blueprint("flexmeasures_api_v1_2", __name__)
flexmeasures_api_v1_3 = Blueprint("flexmeasures_api_v1_3", __name__)
flexmeasures_api_v2_0 = Blueprint("flexmeasures_api_v2_0", __name__)

SUNSET_INFO = [
    dict(
        blueprint=flexmeasures_api_v1,
        api_version_being_sunset="1.0",
        deprecation_date="2022-12-14",
        deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
        sunset_date="2023-05-01",
        sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1.html",
    ),
    dict(
        blueprint=flexmeasures_api_v1_1,
        api_version_being_sunset="1.1",
        deprecation_date="2022-12-14",
        deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
        sunset_date="2023-05-01",
        sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_1.html",
    ),
    dict(
        blueprint=flexmeasures_api_v1_2,
        api_version_being_sunset="1.2",
        deprecation_date="2022-12-14",
        deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
        sunset_date="2023-05-01",
        sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_2.html",
    ),
    dict(
        blueprint=flexmeasures_api_v1_3,
        api_version_being_sunset="1.3",
        deprecation_date="2022-12-14",
        deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
        sunset_date="2023-05-01",
        sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_3.html",
    ),
    dict(
        blueprint=flexmeasures_api_v2_0,
        api_version_being_sunset="2.0",
        deprecation_date="2022-12-14",
        deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
        sunset_date="2023-05-01",
        sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v2_0.html",
    ),
]

for info in SUNSET_INFO:
    deprecate_blueprint(**info)
    sunset_blueprint(**info, rollback_possible=False)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.sunset.routes  # noqa: F401 this is necessary to load the endpoints

    app.register_blueprint(flexmeasures_api_v1, url_prefix="/api/v1")
    app.register_blueprint(flexmeasures_api_v1_1, url_prefix="/api/v1_1")
    app.register_blueprint(flexmeasures_api_v1_2, url_prefix="/api/v1_2")
    app.register_blueprint(flexmeasures_api_v1_3, url_prefix="/api/v1_3")
    app.register_blueprint(flexmeasures_api_v2_0, url_prefix="/api/v2_0")
