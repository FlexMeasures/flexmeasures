from flask import Flask
from flask_security import auth_token_required

from flexmeasures.auth.decorators import account_roles_accepted


def register_at(app: Flask):
    """This can be used to register FlaskViews."""

    from flexmeasures.api.dev.sensors import SensorAPI
    from flexmeasures.api.dev.assets import AssetAPI
    from flexmeasures.api.dev.sensor_data import post_data as post_sensor_data_impl

    dev_api_prefix = "/api/dev"

    SensorAPI.register(app, route_prefix=dev_api_prefix)
    AssetAPI.register(app, route_prefix=dev_api_prefix)

    @app.route(f"{dev_api_prefix}/sensorData", methods=["POST"])
    @auth_token_required
    @account_roles_accepted("MDC", "Prosumer")
    def post_sensor_data():
        """
        Post sensor data to FlexMeasures.

        For example:

        {
            "type": "PostSensorDataRequest",
            "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
            "values": [-11.28, -11.28, -11.28, -11.28],
            "start": "2021-06-07T00:00:00+02:00",
            "duration": "PT1H",
            "unit": "m³/h",
        }

        The above request posts four values for a duration of one hour, where the first
        event start is at the given start time, and subsequent values start in 15 minute intervals throughout the one hour duration.

        The sensor is the one with ID=1.
        The unit has to match the sensor's required unit.
        The resolution of the data has to match the sensor's required resolution, but
        FlexMeasures will attempt to upsample lower resolutions.
        """
        return post_sensor_data_impl()

    # TODO: add GET /sensorData
