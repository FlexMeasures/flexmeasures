import json

from isodate import datetime_isoformat, duration_isoformat
import pandas as pd
from flask_classful import FlaskView, route
from flask_security import auth_token_required
from webargs.flaskparser import use_args

from flexmeasures.api.common.schemas.sensor_data import (
    SensorDataSchema,
    SensorDataDescriptionSchema,
)
from flexmeasures.api.common.utils.api_utils import save_and_enqueue
from flexmeasures import Sensor
from flexmeasures.auth.decorators import account_roles_accepted
from flexmeasures.data.services.time_series import simplify_index
from flexmeasures.utils.unit_utils import convert_units


class SensorDataAPI(FlaskView):

    route_base = "/sensorData"
    decorators = [login_required]

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
        beliefs = SensorDataSchema.load_bdf(sensor_data)
        response, code = save_and_enqueue(beliefs)
        response.update(type="PostSensorDataResponse")
        return response, code

    @route("/", methods=["GET"])
    @use_args(
        SensorDataDescriptionSchema(),
        location="query",
    )
    def get(self, sensor_data_description):
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
        # todo: move some of the below logic to the dump_bdf (serialize) method on the schema
        sensor: Sensor = sensor_data_description["sensor"]
        start = sensor_data_description["start"]
        duration = sensor_data_description["duration"]
        end = sensor_data_description["start"] + duration
        unit = sensor_data_description["unit"]

        df = simplify_index(
            sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                horizons_at_least=sensor_data_description.get("horizon", None),
                beliefs_before=sensor_data_description.get("prior", None),
                one_deterministic_belief_per_event=True,
                as_json=False,
            )
        )

        # Convert to desired time range
        index = pd.date_range(
            start=start, end=end, freq=sensor.event_resolution, closed="left"
        )
        df = df.reindex(index)

        # Convert to desired unit
        values = convert_units(
            df["event_value"],
            from_unit=sensor.unit,
            to_unit=unit,
        )

        # Convert NaN to null
        values = values.where(pd.notnull(values), None)

        # Form the response
        response = dict(
            values=values.tolist(),
            start=datetime_isoformat(start),
            duration=duration_isoformat(duration),
            unit=unit,
        )
        response.update(type="GetSensorDataResponse")
        return json.dumps(response)
