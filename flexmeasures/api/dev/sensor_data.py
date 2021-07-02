from webargs.flaskparser import use_args

from flexmeasures.data.config import db
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.api.common.schemas.sensor_data import SensorDataSchema


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
    TimedBelief.add_to_session(session=db.session, beliefs_data_frame=beliefs)
    db.session.commit()
    return dict(status="ok")


def get_data():
    # use data.models.time_series.Sensor::search_beliefs()
    pass
