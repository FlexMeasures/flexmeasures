"""
Endpoints under development. Use at your own risk.
"""

from flask import Flask


def register_at(app: Flask):
    """This can be used to register FlaskViews."""

    from flexmeasures.api.dev.sensors import SensorAPI
    from flexmeasures.api.dev.sensors import AssetAPI
    from flexmeasures.api.dev.annotations import AnnotationAPI

    dev_api_prefix = "/api/dev"

    SensorAPI.register(app, route_prefix=dev_api_prefix)
    AssetAPI.register(app, route_prefix=dev_api_prefix)
    AnnotationAPI.register(app, route_prefix=dev_api_prefix)
