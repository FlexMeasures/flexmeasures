from flask import Flask


def register_at(app: Flask):
    """This can be used to register FlaskViews."""

    from flexmeasures.api.dev.sensors import SensorAPI

    SensorAPI.register(app, route_prefix="/api/dev")
