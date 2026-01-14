from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
import sqlalchemy as sa


from redis.exceptions import ConnectionError
from flexmeasures.data import db


def _check_sql_database():
    try:
        db.session.execute(sa.text("SELECT 1")).first()
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
    @as_json
    def is_ready(self):
        """
        .. :quickref: Public; Check readiness status
        ---
        get:
          summary: Get readiness status
          description: |
            Health check endpoint to verify if core services required by FlexMeasures are ready.

          responses:
            200:
              description: All required services are operational.
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      database_sql:
                        type: boolean
                        example: true
                      database_redis:
                        type: boolean
                        example: false
          tags:
            - Public
        """

        status = {
            "database_sql": _check_sql_database(),
        }

        if current_app.config.get("FLEXMEASURES_REDIS_PASSWORD") is not None:
            status["database_redis"] = _check_redis()

        if all(status.values()):
            return status, 200
        else:
            return status, 503
