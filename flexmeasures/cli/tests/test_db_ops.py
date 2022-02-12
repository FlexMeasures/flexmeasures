import pytest

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.skip_github
def test_resample_sensor_data(app, db, setup_beliefs):
    """Check resampling market data from hourly to 30 minute resolution."""

    from flexmeasures.cli.db_ops import resample_sensor_data

    sensor = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    beliefs_before = sensor.search_beliefs(
        most_recent_beliefs_only=False,
    )

    # Check whether fixtures have flushed
    assert sensor.id is not None

    cli_input = {
        "sensor-id": sensor.id,
        "event-resolution": 30,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(
        resample_sensor_data, to_flags(cli_input) + ["--skip-integrity-check"]
    )

    # Check result for success
    assert "Successfully resampled" in result.output

    # Check that we now have twice as much data for this sensor
    sensor = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    beliefs_after = sensor.search_beliefs(
        most_recent_beliefs_only=False,
    )
    assert len(beliefs_after) == 2 * len(beliefs_before)

    # Checksum
    assert beliefs_after["event_value"].sum() == 2 * beliefs_before["event_value"].sum()
