"""
Endpoints that are not part of the official API: endpoints under development, and endpoints supporting the FlexMeasures UI.
Use at your own risk, as they may change or disappear in any FlexMeasures version.
"""

from flask import Flask


def register_at(app: Flask):
    """This can be used to register FlaskViews."""

    from flexmeasures.api.dev.sensors import SensorAPI
    from flexmeasures.api.dev.sensors import AssetAPI
    from flexmeasures.api.dev.session import SessionAPI

    dev_api_prefix = "/api/dev"

    SensorAPI.register(app, route_prefix=dev_api_prefix)
    AssetAPI.register(app, route_prefix=dev_api_prefix)
    SessionAPI.register(app, route_prefix=dev_api_prefix)
