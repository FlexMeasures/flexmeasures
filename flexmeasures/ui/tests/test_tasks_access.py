"""The RQ dashboard (/tasks) is for admins in every mode and environment.

It shows the arguments, results and errors of every account's jobs, and can delete jobs and empty queues.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import rq_dashboard
from flask_security import login_user, logout_user
from werkzeug.exceptions import Forbidden

from flexmeasures.data import db
from flexmeasures.data.models.user import User
from flexmeasures.ui import register_rq_dashboard


class RecordingBlueprint:
    """Stands in for the dashboard's blueprint, which the test app has registered already, to see which guards get installed."""

    def __init__(self):
        self.guards = []
        self.before_request_funcs = {None: self.guards}

    def before_request(self, guard):
        self.guards.append(guard)
        return guard


def _refused(guards) -> bool:
    """Whether one of the guards refuses the current request."""
    for guard in guards:
        try:
            if guard() is not None:
                return True
        except Forbidden:
            return True
    return False


@pytest.mark.parametrize(
    "env, mode",
    [
        ("production", "demo"),
        ("documentation", ""),
        ("production", ""),
    ],
)
def test_rq_dashboard_admits_only_admins(
    app, setup_roles_users, monkeypatch, env, mode
):
    blueprint = RecordingBlueprint()
    monkeypatch.setattr(rq_dashboard, "blueprint", blueprint)
    host_app = SimpleNamespace(
        config={"FLEXMEASURES_ENV": env, "FLEXMEASURES_MODE": mode},
        register_blueprint=lambda *args, **kwargs: None,
    )
    register_rq_dashboard(host_app)

    with app.test_request_context("/tasks/"):
        assert _refused(blueprint.guards), "an anonymous visitor got in"
    with app.test_request_context("/tasks/"):
        login_user(db.session.get(User, setup_roles_users["Test Prosumer User"]))
        assert _refused(blueprint.guards), "a logged-in non-admin got in"
        logout_user()
    with app.test_request_context("/tasks/"):
        login_user(db.session.get(User, setup_roles_users["Test Admin User"]))
        assert not _refused(blueprint.guards), "an admin was refused"
        logout_user()


def test_rq_dashboard_refuses_non_admins(client, as_prosumer_user1):
    response = client.get("/tasks/")
    assert response.status_code == 403


def test_rq_dashboard_guard_survives_another_app(app):
    """Creating another app in the same process, as the documentation build does once per API page, works and keeps one guard.

    The test app has registered the dashboard's blueprint already, and Flask refuses new hooks on a registered blueprint.
    """
    host_app = SimpleNamespace(
        config={}, register_blueprint=lambda *args, **kwargs: None
    )
    register_rq_dashboard(host_app)
    register_rq_dashboard(host_app)

    guards = rq_dashboard.blueprint.before_request_funcs.get(None, [])
    assert [guard.__name__ for guard in guards].count("rq_dashboard_admin_auth") == 1
