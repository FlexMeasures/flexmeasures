from webargs.flaskparser import use_args

from flexmeasures.api.common.schemas.sensor_data import SensorDataSchema
from flexmeasures.api.common.utils.api_utils import save_to_db


@use_args(
    SensorDataSchema(),
    location="json",
)
def post_data(sensor_data):
    """POST to /sensorData

    Experimental dev feature which uses timely-beliefs
    to create and save the data structure.
    """
    beliefs = SensorDataSchema.load_bdf(sensor_data)
    response, code = save_to_db(beliefs)
    response.update(type="PostSensorDataResponse")
    return response, code


def get_data():
    """ GET from /sensorData"""
    # - use data.models.time_series.Sensor::search_beliefs() - might need to add a belief_horizon parameter
    # - create the serialize method on the schema, to turn the resulting BeliefsDataFrame
    #   to the JSON the API should respond with.
    pass
