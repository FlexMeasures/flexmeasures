from datetime import datetime, timedelta

from flask import url_for
import pytz
import isodate

from bvp.api.v1.tests.utils import get_auth_token, get_task_run, post_task_run


def test_api_task_run_post_unauthorized_wrong_role(client):
    url = url_for("bvp_api_v1.post_task_run")
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    post_req_params = dict(
        query_string={"name": "my-task"}, headers={"Authentication-Token": auth_token}
    )
    task_run = client.post(url, **post_req_params)
    assert task_run.status_code == 403
    assert b"Forbidden" in task_run.data
    # While we are on it, test if the unauth handler correctly returns json if we set the content-type
    post_req_params.update(
        headers={"Authentication-Token": auth_token, "Content-Type": "application/json"}
    )
    task_run = client.post(url, **post_req_params)
    assert task_run.status_code == 403
    assert "Forbidden" in task_run.json["message"]


def test_api_task_run_get_no_name(client):
    task_run = get_task_run(client, "")
    assert task_run.status_code == 400
    assert task_run.json["error"] == "No task name given."


def test_api_task_run_post_no_name(client):
    task_run = post_task_run(client, "")
    assert task_run.status_code == 400
    assert task_run.json["error"] == "No task name given."


def test_api_task_run_get_recent_entry(client):
    task_run = get_task_run(client, "task-B")
    assert task_run.status_code == 200
    task_time = isodate.parse_datetime(task_run.json.get("datetime"))
    utcnow = datetime.utcnow().replace(tzinfo=pytz.utc)
    assert task_time <= utcnow
    assert task_time >= utcnow - timedelta(minutes=1)
    assert task_run.json.get("status") is False


def test_api_task_run_get_older_entry_then_update(client):
    task_run = get_task_run(client, "task-A")
    assert task_run.status_code == 200
    task_time = isodate.parse_datetime(task_run.json.get("datetime"))
    utcnow = datetime.utcnow().replace(tzinfo=pytz.utc)
    assert task_time <= utcnow - timedelta(days=1)
    assert task_time >= utcnow - timedelta(days=1, minutes=1)
    assert task_run.json.get("status") is True
    # update the latest run of this task (also report that it failed)
    task_update = post_task_run(client, "task-A", False)
    assert task_update.status_code == 200
    task_run = get_task_run(client, "task-A")
    task_time = isodate.parse_datetime(task_run.json.get("datetime"))
    utcnow = datetime.utcnow().replace(tzinfo=pytz.utc)
    assert task_time <= utcnow
    assert task_time >= utcnow - timedelta(minutes=1)
    assert task_run.json.get("status") is False
