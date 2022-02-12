from flexmeasures.data.models.time_series import Sensor


def test_invoking(app, db, setup_beliefs):
    """Check what invoking does to the session."""

    from flexmeasures.cli.data_show import list_accounts

    sensor_before_invoke = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    assert sensor_before_invoke in db.session

    # Check whether fixtures have flushed
    assert sensor_before_invoke.id is not None

    runner = app.test_cli_runner()
    runner.invoke(list_accounts)

    # Check that the sensor is still there
    assert sensor_before_invoke in db.session  # fails
    sensor_after_invoke = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    assert (
        sensor_after_invoke == sensor_before_invoke
    )  # also fails, because sensor_after_invoke is None
