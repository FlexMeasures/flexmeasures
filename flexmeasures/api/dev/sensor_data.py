from datetime import timedelta

from flask_login import current_user
from werkzeug.exceptions import abort
from webargs.flaskparser import use_args
import pandas as pd
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.api.common.schemas.sensor_data import SensorDataSchema
from flexmeasures.utils.time_utils import timedelta_to_pandas_freq_str


# TODO
# - SensorDataDescriptionSchema (with type?)
# - SensorDataSchema (+values, de-serialize to BDF)
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
    # TODO: check unit against sensor.unit? Can we leave it out?
    # TODO: The following could go to SensorDataSchema._deserialize
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
        sensor=sensor_data["connection"],
        belief_horizon=timedelta(hours=0),
    )
    # save beliefs
    # TODO: bdf.save
    print(bdf)
    return dict(status="ok")


def get_data():
    pass
