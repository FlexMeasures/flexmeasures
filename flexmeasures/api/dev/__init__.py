from flask import Flask
from flask_security import auth_token_required, roles_accepted


def register_at(app: Flask):
    """This can be used to register FlaskViews."""

    from flexmeasures.api.dev.sensors import SensorAPI
    from flexmeasures.api.dev.sensor_data import post_data as send_sensor_data

    SensorAPI.register(app, route_prefix="/api/dev")

    @app.route("/sensorData", methods=["POST"])
    @auth_token_required
    @roles_accepted("admin", "MDC")
    def post_sensor_data():
        return send_sensor_data()

    # TODO: add GET /sensorData
