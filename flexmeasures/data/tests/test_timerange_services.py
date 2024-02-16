from flexmeasures.data.services.timerange import get_timerange
from flexmeasures.tests.utils import get_test_sensor


def test_get_sensor_timerange(setup_beliefs, db):
    """Test getting the timerange of a sensor."""

    # Set a reference for the number of beliefs stored and their belief times
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs()

    expected_timerange = bdf.event_starts[0], bdf.event_ends[-1]
    timerange = get_timerange(sensor_ids=[sensor.id])

    assert timerange == expected_timerange
