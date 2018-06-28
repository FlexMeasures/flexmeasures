from typing import List
from datetime import datetime, timedelta
import pytz

import pytest

from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password


@pytest.fixture(scope="function", autouse=True)
def setup_api_test_data(db):
    """
    Adding the task-runner
    """
    print("Setting up data for API tests on %s" % db.engine)

    from bvp.data.models.user import User, Role
    from bvp.data.models.assets import Asset, AssetType
    from bvp.data.models.task_runs import LatestTaskRun

    # Create test roles

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    test_task_runner_role = user_datastore.create_role(
        name="task-runner", description="A node running repeated tasks."
    )
    test_prosumer_role = user_datastore.find_role(
        "Prosumer"
    )  # created in top-level conftest
    test_mdc_role = user_datastore.create_role(
        name="MDC",
        description="A Meter Data Company allowed to post verified meter data.",
    )

    # Create test users

    test_task_runner = user_datastore.create_user(
        username="test user",
        email="task_runner@seita.nl",
        password=hash_password("testtest"),
    )
    user_datastore.add_role_to_user(test_task_runner, test_task_runner_role)

    user_datastore.create_user(
        username="test user without roles",
        email="test_user@seita.nl",
        password=hash_password("testtest"),
    )

    test_prosumer = user_datastore.create_user(
        username="test Prosumer",
        email="test_prosumer_user@seita.nl",
        password=hash_password("testtest"),
    )
    user_datastore.add_role_to_user(test_prosumer, test_prosumer_role)
    user_datastore.add_role_to_user(test_prosumer, test_mdc_role)

    # Create 3 test assets

    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["CS 1", "CS 2", "CS 3"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            asset_type_name="test-type",
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
        )
        asset.owner = test_prosumer
        assets.append(asset)
        db.session.add(asset)

    # More task stuff

    older_task = LatestTaskRun(
        name="task-A",
        status=True,
        datetime=datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(days=1),
    )
    recent_task = LatestTaskRun(name="task-B", status=False)
    db.session.add(older_task)
    db.session.add(recent_task)

    print("Done setting up data for API tests")
