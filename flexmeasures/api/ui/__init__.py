"""
Endpoints supporting the FlexMeasures UI.

They are not part of the official API, and not meant for external UIs:
they serve FlexMeasures' own UI, which is deployed together with the server, so they may change in any FlexMeasures version.
For integrations, use the official API (see `flexmeasures.api.v3_0`).
"""

from flask import Flask

UI_API_PREFIX = "/api/ui"

# These endpoints used to be served under /api/dev, and still are, on the off chance that something outside FlexMeasures calls them there.
# The old prefix is to be dropped in FlexMeasures v2.
LEGACY_DEV_API_PREFIX = "/api/dev"


def register_at(app: Flask):
    """This can be used to register FlaskViews."""

    from flexmeasures.api.ui.sensors import (
        AssetAPI,
        LegacyDevAssetAPI,
        LegacyDevSensorAPI,
        SensorAPI,
    )
    from flexmeasures.api.ui.session import LegacyV3SessionAPI, SessionAPI

    SensorAPI.register(app, route_prefix=UI_API_PREFIX)
    AssetAPI.register(app, route_prefix=UI_API_PREFIX)

    SessionAPI.register(app, route_prefix=UI_API_PREFIX)

    LegacyDevSensorAPI.register(app, route_prefix=LEGACY_DEV_API_PREFIX)
    LegacyDevAssetAPI.register(app, route_prefix=LEGACY_DEV_API_PREFIX)
    # Two session endpoints were released under v3 of the official API, where they keep working, undocumented, until v4.
    LegacyV3SessionAPI.register(app, route_prefix="/api/v3_0")
