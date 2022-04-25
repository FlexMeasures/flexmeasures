from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json

from flexmeasures.data import db


def _check_sql_database():
    try:
        db.session.execute("SELECT 1").first()
        return True
    except Exception:  # noqa: B902
        current_app.logger.exception("Database down or undetected")
        return False


class HealthAPI(FlaskView):

    route_base = "/health"
    trailing_slash = False

    @route("/ready", methods=["GET"])
    @as_json
    def is_ready(self):
        """
        Get readiness status
        """
        status = {"database_sql": _check_sql_database()}  # TODO: check redis
        if all(status.values()):
            return status, 200
        else:
            return status, 503
