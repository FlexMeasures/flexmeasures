from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from webargs.flaskparser import use_kwargs
from marshmallow import fields


from redis.exceptions import ConnectionError
from flexmeasures.data import db


def _check_sql_database():
    try:
        db.session.execute("SELECT 1").first()
        return True
    except Exception:  # noqa: B902
        current_app.logger.exception("Database down or undetected")
        return False


def _check_redis() -> bool:
    """Check status of the redis instance

    :return: True if the redis instance is active, False otherwise
    """
    try:
        current_app.redis_connection.ping()
        return True
    except ConnectionError:
        return False


class HealthAPI(FlaskView):

    route_base = "/health"
    trailing_slash = False

    @route("/ready", methods=["GET"])
    @use_kwargs(
        {
            "expect_redis": fields.Boolean(required=False, default=False),
        },
        location="query",
    )
    @as_json
    def is_ready(self, **kwargs):
        """
        Get readiness status

        .. :quickref: Health; Get readiness status

        **Optional fields**
        - "expect_redis": flag to check for a redis connection or not.

        **Example response:**

        .. sourcecode:: json

            {
                'database_sql': True,
                'database_redis': False
            }

        """

        status = {
            "database_sql": _check_sql_database(),
        }

        if kwargs.get("expect_redis", False):
            status["database_redis"] = _check_redis()

        if all(status.values()):
            return status, 200
        else:
            return status, 503
