"""Requeueing jobs on the task dashboard needs an admin and a POST request."""

import pytest

from flexmeasures.ui.tests.utils import login, logout


@pytest.fixture(autouse=True)
def dashboard_uses_test_redis(app, clean_redis, monkeypatch):
    """rq-dashboard connects to the Redis it finds on the app before our access check runs."""
    monkeypatch.setattr(app, "redis_conn", app.redis_connection, raising=False)


@pytest.fixture
def as_admin_reader(client):
    login(client, "test_admin_reader_user@seita.nl", "testtest")
    yield
    logout(client)


@pytest.mark.parametrize(
    "url", ["/tasks/requeue/scheduling", "/tasks/job/some-job-id/requeue"]
)
def test_admin_reader_cannot_requeue(client, as_admin_reader, url):
    response = client.post(url)
    assert response.status_code == 403


def test_admin_reader_can_still_look(client, as_admin_reader):
    response = client.get("/tasks/", follow_redirects=True)
    assert response.status_code == 200


def test_requeue_all_is_refused_on_get(client, as_admin):
    """A link (or an image) on another site must not make an admin's browser requeue all failed jobs."""
    response = client.get("/tasks/requeue/scheduling")
    assert response.status_code == 405


def test_admin_can_requeue_with_post(client, as_admin):
    response = client.post("/tasks/requeue/scheduling")
    assert response.status_code == 200
