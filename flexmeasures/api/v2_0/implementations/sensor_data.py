from flask_classful import FlaskView, route
from flask_security import auth_token_required
from webargs.flaskparser import use_args

from flexmeasures.api.common.schemas.sensor_data import SensorDataSchema
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.auth.decorators import account_roles_accepted


class SensorDataAPI(FlaskView):

    route_base = "/sensorData"

    @auth_token_required
    @account_roles_accepted("MDC", "Prosumer")
    @use_args(
        SensorDataSchema(),
        location="json",
    )
    @route("/", methods=["POST"])
    def post(self, sensor_data):
        """
        Post sensor data to FlexMeasures.

        .. :quickref: Data; Upload sensor data

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
        beliefs = SensorDataSchema.load_bdf(sensor_data)
        response, code = save_and_enqueue(beliefs)
        response.update(type="PostSensorDataResponse")
        return response, code

    @route("/", methods=["GET"])
    def get(self):
        """Get sensor data from FlexMeasures.

        .. :quickref: Data; Download sensor data
        """
        # - use data.models.time_series.Sensor::search_beliefs() - might need to add a belief_horizon parameter
        # - create the serialize method on the schema, to turn the resulting BeliefsDataFrame
        #   to the JSON the API should respond with.
        pass
