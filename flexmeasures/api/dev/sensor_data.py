from datetime import timedelta

from flask_login import current_user
from werkzeug.exceptions import abort
from webargs.flaskparser import use_args
import pandas as pd
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.config import db
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.api.common.schemas.sensor_data import SensorDataSchema
from flexmeasures.utils.time_utils import timedelta_to_pandas_freq_str


# TODO
# - stub for get_data (and for serializing to BDF)
# - implement post_data
# - add tests


@use_args(
    SensorDataSchema(),
    location="json",
)
def post_data(sensor_data):
    """POST to /sensorData

    Experimental dev feature which uses timely-beliefs
    to create and save the data structure.
    """
    source = DataSource.query.get(current_user.id)
    if not source:
        raise abort(400, f"User {current_user.id} is not an accepted data source.")
    # TODO: The following could go to SensorDataSchema._deserialize if we want it to return a bdf
    num_values = len(sensor_data["values"])
    step_duration = sensor_data["duration"] / num_values
    dt_index = pd.date_range(
        sensor_data["start"],
        periods=num_values,
        freq=timedelta_to_pandas_freq_str(step_duration),
        tz=sensor_data["start"].tzinfo,
    )
    s = pd.Series(sensor_data["values"], index=dt_index)
    bdf: BeliefsDataFrame = BeliefsDataFrame(
        s,
        source=source,
        sensor=sensor_data["sensor"],
        belief_horizon=timedelta(hours=0),
    )
    # save beliefs
    TimedBelief.add_to_session(session=db.session, beliefs_data_frame=bdf)
    db.session.commit()
    return dict(status="ok")


def get_data():
    # use data.models.time_series.Sensor::search_beliefs()
    pass
