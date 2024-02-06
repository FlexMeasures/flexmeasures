from sqlalchemy import select

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.timerange import get_timerange


def test_get_sensor_timerange(setup_beliefs, db):
    """Test getting the timerange of a sensor."""

    # Set a reference for the number of beliefs stored and their belief times
    sensor = db.session.execute(
        select(Sensor).filter_by(name="epex_da")
    ).scalar_one_or_none()
    bdf = sensor.search_beliefs()

    expected_timerange = bdf.event_starts[0], bdf.event_ends[-1]
    timerange = get_timerange(sensor_ids=[sensor.id])

    assert timerange == expected_timerange
