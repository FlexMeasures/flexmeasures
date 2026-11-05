from sqlalchemy import func, select

from flexmeasures.cli.tests.utils import check_command_ran_without_error
from flexmeasures.data.models.time_series import TimedBelief


def test_delete_beliefs_for_sensor(app, fresh_db, setup_dummy_data_fresh_db):
    """Delete the selected sensor's beliefs while leaving other sensors' data intact."""
    from flexmeasures.cli.data_delete import delete_beliefs

    sensor_id, other_sensor_id, _, _ = setup_dummy_data_fresh_db
    runner = app.test_cli_runner()

    result = runner.invoke(delete_beliefs, ["--sensor", str(sensor_id), "--force"])

    check_command_ran_without_error(result)
    assert "Removing 200 beliefs" in result.output
    assert "0 beliefs left" in result.output
    for current_id, expected_count in [(sensor_id, 0), (other_sensor_id, 200)]:
        count = fresh_db.session.scalar(
            select(func.count())
            .select_from(TimedBelief)
            .where(TimedBelief.sensor_id == current_id)
        )
        assert count == expected_count


def test_delete_unchanged_beliefs_when_none_are_unchanged(
    app, fresh_db, setup_dummy_data_fresh_db
):
    """Report no unchanged forecasts or measurements for distinct events."""
    from flexmeasures.cli.data_delete import delete_unchanged_beliefs

    sensor_id = setup_dummy_data_fresh_db[0]
    result = app.test_cli_runner().invoke(
        delete_unchanged_beliefs, ["--sensor", str(sensor_id)]
    )

    check_command_ran_without_error(result)
    assert "0 unchanged beliefs found" in result.output
    assert fresh_db.session.scalar(
        select(func.count())
        .select_from(TimedBelief)
        .where(TimedBelief.sensor_id == sensor_id)
    ) == 200
