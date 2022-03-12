import json

from flask_classful import FlaskView, route
from flask_security import auth_token_required
from timely_beliefs import BeliefsDataFrame
from webargs.flaskparser import use_args

from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.utils.api_utils import save_and_enqueue


class SensorDataAPI(FlaskView):

    route_base = "/sensorData"
    decorators = [auth_token_required]

    @use_args(
        PostSensorDataSchema(),
        location="json",
    )
    @route("/", methods=["POST"])
    def post(self, bdf: BeliefsDataFrame):
        """
        Post sensor data to FlexMeasures.

        .. :quickref: Data; Upload sensor data

        **Example request**

        .. code-block:: json

            {
                "type": "PostSensorDataRequest",
                "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
                "values": [-11.28, -11.28, -11.28, -11.28],
                "start": "2021-06-07T00:00:00+02:00",
                "duration": "PT1H",
                "unit": "m³/h"
            }

        The above request posts four values for a duration of one hour, where the first
        event start is at the given start time, and subsequent values start in 15 minute intervals throughout the one hour duration.

        The sensor is the one with ID=1.
        The unit has to be convertible to the sensor's unit.
        The resolution of the data has to match the sensor's required resolution, but
        FlexMeasures will attempt to upsample lower resolutions.
        """
        response, code = save_and_enqueue(bdf)
        response.update(type="PostSensorDataResponse")
        return response, code

    @route("/", methods=["GET"])
    @use_args(
        GetSensorDataSchema(),
        location="query",
    )
    def get(self, response: dict):
        """Get sensor data from FlexMeasures.

        .. :quickref: Data; Download sensor data

        **Example request**

        .. code-block:: json

            {
                "type": "GetSensorDataRequest",
                "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
                "start": "2021-06-07T00:00:00+02:00",
                "duration": "PT1H",
                "unit": "m³/h"
            }

        The unit has to be convertible from the sensor's unit.
        """
        response.update(type="GetSensorDataResponse")
        return json.dumps(response)
