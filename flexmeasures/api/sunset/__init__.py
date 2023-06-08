from flask import Flask, Blueprint

from flexmeasures.api.common.utils.deprecation_utils import (
    deprecate_blueprint,
    sunset_blueprint,
)


# The api blueprint. It is registered with the Flask app (see register_at)
flexmeasures_api_v1 = Blueprint("flexmeasures_api_v1", __name__)
deprecate_blueprint(
    flexmeasures_api_v1,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset",
    sunset_date="2023-05-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1.html",
)
sunset_blueprint(
    flexmeasures_api_v1,
    "1.0",
    "https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1.html",
    rollback_possible=False,
)

# The api blueprint. It is registered with the Flask app (see app.py)
flexmeasures_api_v1_1 = Blueprint("flexmeasures_api_v1_1", __name__)
deprecate_blueprint(
    flexmeasures_api_v1_1,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/v1_1.html",
    sunset_date="2023-05-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_1.html",
)
sunset_blueprint(
    flexmeasures_api_v1_1,
    "1.1",
    "https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_1.html",
    rollback_possible=False,
)

# The api blueprint. It is registered with the Flask app (see app.py)
flexmeasures_api_v1_2 = Blueprint("flexmeasures_api_v1_2", __name__)
deprecate_blueprint(
    flexmeasures_api_v1_2,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/v1_2.html",
    sunset_date="2023-05-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_2.html",
)
sunset_blueprint(
    flexmeasures_api_v1_2,
    "1.2",
    "https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_2.html",
    rollback_possible=False,
)

# The api blueprint. It is registered with the Flask app (see app.py)
flexmeasures_api_v1_3 = Blueprint("flexmeasures_api_v1_3", __name__)
deprecate_blueprint(
    flexmeasures_api_v1_3,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/v1_3.html",
    sunset_date="2023-05-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_3.html",
)
sunset_blueprint(
    flexmeasures_api_v1_3,
    "1.3",
    "https://flexmeasures.readthedocs.io/en/v0.13.0/api/v1_3.html",
    rollback_possible=False,
)

flexmeasures_api_v2_0 = Blueprint("flexmeasures_api_v2_0", __name__)
deprecate_blueprint(
    flexmeasures_api_v2_0,
    deprecation_date="2022-12-14",
    deprecation_link="https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html",
    sunset_date="2023-05-01",
    sunset_link="https://flexmeasures.readthedocs.io/en/v0.13.0/api/v2_0.html",
)
sunset_blueprint(
    flexmeasures_api_v2_0,
    "2.0",
    "https://flexmeasures.readthedocs.io/en/v0.13.0/api/v2_0.html",
    rollback_possible=False,
)


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    import flexmeasures.api.v1.routes  # noqa: F401 this is necessary to load the endpoints
    import flexmeasures.api.v1_1.routes  # noqa: F401 this is necessary to load the endpoints
    import flexmeasures.api.v1_2.routes  # noqa: F401 this is necessary to load the endpoints
    import flexmeasures.api.v1_3.routes  # noqa: F401 this is necessary to load the endpoints
    import flexmeasures.api.v2_0.routes  # noqa: F401 this is necessary to load the endpoints

    app.register_blueprint(flexmeasures_api_v1, url_prefix="/api/v1")
    app.register_blueprint(flexmeasures_api_v1_1, url_prefix="/api/v1_1")
    app.register_blueprint(flexmeasures_api_v1_2, url_prefix="/api/v1_2")
    app.register_blueprint(flexmeasures_api_v1_3, url_prefix="/api/v1_3")
    app.register_blueprint(flexmeasures_api_v2_0, url_prefix="/api/v2_0")
