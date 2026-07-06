import pytest
from sqlalchemy import select, text
from timely_beliefs.beliefs.materialized_views import (
    MOST_RECENT_BELIEFS_MVIEW,
    create_mview_ddl,
    create_mview_indexes_ddl,
    drop_mview_ddl,
)

from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.materialized_views import MVIEW_REFRESH_TASK_NAME


@pytest.fixture(scope="function")
def setup_mview(fresh_db):
    """Create the materialized view (as the corresponding migration would) and let the app know it exists."""
    from flexmeasures.data import config as data_config

    fresh_db.session.execute(text(drop_mview_ddl()))
    fresh_db.session.execute(text(create_mview_ddl(TimedBelief)))
    fresh_db.session.execute(text(create_mview_indexes_ddl()))

    # The app checks for the view at startup, i.e. before this fixture created it
    original_mview = data_config.most_recent_beliefs_mview
    data_config.most_recent_beliefs_mview = MOST_RECENT_BELIEFS_MVIEW
    yield
    data_config.most_recent_beliefs_mview = original_mview
    # Commit the drop, because the refresh CLI command commits, thereby persisting the view
    fresh_db.session.execute(text(drop_mview_ddl()))
    fresh_db.session.commit()


def test_refresh_materialized_views(app, fresh_db, setup_mview):
    """The CLI command should refresh the view and record its run in the latest_task_run table."""
    from flexmeasures.cli.db_ops import refresh_materialized_views

    runner = app.test_cli_runner()
    result = runner.invoke(refresh_materialized_views)
    assert result.exit_code == 0

    task_run = fresh_db.session.get(LatestTaskRun, MVIEW_REFRESH_TASK_NAME)
    assert task_run is not None
    assert task_run.status is True


def test_refresh_materialized_views_failure(app, fresh_db):
    """Without the view in place, the CLI command should fail and record the failed run."""
    from flexmeasures.cli.db_ops import refresh_materialized_views

    runner = app.test_cli_runner()
    result = runner.invoke(refresh_materialized_views)
    assert result.exit_code != 0

    task_run = fresh_db.session.get(LatestTaskRun, MVIEW_REFRESH_TASK_NAME)
    assert task_run is not None
    assert task_run.status is False


def test_search_beliefs_with_mview(app, fresh_db, setup_mview, setup_beliefs_fresh_db):
    """After a refresh, searching via the materialized view should match searching the beliefs table."""
    from flexmeasures.cli.db_ops import refresh_materialized_views
    import pandas as pd

    from flexmeasures.data.models.time_series import Sensor

    # Commit the beliefs before refreshing, so the view can see them
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(refresh_materialized_views)
    assert result.exit_code == 0

    sensor = fresh_db.session.execute(
        select(Sensor).filter_by(name="epex_da")
    ).scalar_one()

    bdf_live = sensor.search_beliefs(
        most_recent_beliefs_only=True, use_materialized_view=False
    )
    assert not bdf_live.empty

    bdf_mview = sensor.search_beliefs(
        most_recent_beliefs_only=True, use_materialized_view=True
    )
    pd.testing.assert_frame_equal(bdf_mview, bdf_live)

    # Also without the live tail (i.e. from the view alone), because all data was recorded before the refresh
    bdf_mview_only = sensor.search_beliefs(
        most_recent_beliefs_only=True,
        use_materialized_view=True,
        include_live_tail=False,
    )
    pd.testing.assert_frame_equal(bdf_mview_only, bdf_live)
