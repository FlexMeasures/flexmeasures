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
    print("Setting up data for API task runner tests on %s" % db.engine)

    from flexmeasures.data.models.user import User, Role
    from flexmeasures.data.models.task_runs import LatestTaskRun

    # Create test role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    test_task_runner_role = user_datastore.create_role(
        name="task-runner", description="A node running repeated tasks."
    )

    # Create test user

    test_task_runner = user_datastore.create_user(
        username="test user",
        email="task_runner@seita.nl",
        password=hash_password("testtest"),
    )
    user_datastore.add_role_to_user(test_task_runner, test_task_runner_role)

    # More task stuff

    older_task = LatestTaskRun(
        name="task-A",
        status=True,
        datetime=datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(days=1),
    )
    recent_task = LatestTaskRun(name="task-B", status=False)
    db.session.add(older_task)
    db.session.add(recent_task)

    print("Done setting up data for API task runner tests")
