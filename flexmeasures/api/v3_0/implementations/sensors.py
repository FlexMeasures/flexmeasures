import json

from flask_classful import FlaskView, route
from flask_security import auth_required
from timely_beliefs import BeliefsDataFrame
from webargs.flaskparser import use_args

from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.utils.api_utils import save_and_enqueue


class SensorAPI(FlaskView):

    route_base = "/sensors"
    trailing_slash = False
    decorators = [auth_required()]

    @route("/data", methods=["POST"])
    @use_args(
        PostSensorDataSchema(),
        location="json",
    )
    def post_data(self, bdf: BeliefsDataFrame):
        """
        Post sensor data to FlexMeasures.

        .. :quickref: Data; Upload sensor data

        **Example request**

        .. code-block:: json

            {
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
        return response, code

    @route("/data", methods=["GET"])
    @use_args(
        GetSensorDataSchema(),
        location="query",
    )
    def get_data(self, response: dict):
        """Get sensor data from FlexMeasures.

        .. :quickref: Data; Download sensor data

        **Example request**

        .. code-block:: json

            {
                "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
                "start": "2021-06-07T00:00:00+02:00",
                "duration": "PT1H",
                "unit": "m³/h"
            }

        The unit has to be convertible from the sensor's unit.
        """
        return json.dumps(response)
