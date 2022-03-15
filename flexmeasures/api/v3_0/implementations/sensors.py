import json

from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from timely_beliefs import BeliefsDataFrame
from webargs.flaskparser import use_args, use_kwargs

from flexmeasures.api.common.schemas.sensor_data import (
    GetSensorDataSchema,
    PostSensorDataSchema,
)
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.services.sensors import get_sensors

sensors_schema = SensorSchema(many=True)


@use_kwargs(
    {
        "account": AccountIdField(
            data_key="account_id", load_default=AccountIdField.load_current
        ),
    },
    location="query",
)
@permission_required_for_context("read", arg_name="account")
@as_json
def get(account: Account):
    """List sensors of an account."""
    sensors = get_sensors(account_name=account.name)
    return sensors_schema.dump(sensors), 200


class SensorAPI(FlaskView):

    route_base = "/sensors"
    trailing_slash = False
    decorators = [auth_required()]

    def index(self):
        """API endpoint to get sensors.

        .. :quickref: Sensor; Download sensor list
        """
        return get()

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
