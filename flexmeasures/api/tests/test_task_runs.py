from datetime import datetime, timedelta

from flask import url_for
import pytz
import isodate

from flexmeasures.api.tests.utils import get_auth_token, get_task_run, post_task_run
from flexmeasures.data.auth_setup import (
    FORBIDDEN_ERROR_STATUS,
    FORBIDDEN_STATUS_CODE,
    FORBIDDEN_ERROR_CLASS,
    UNAUTH_STATUS_CODE,
)


def test_api_task_run_post_unauthorized_wrong_role(client):
    url = url_for("flexmeasures_api_ops.post_task_run")
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    post_req_params = dict(
        query_string={"name": "my-task"}, headers={"Authorization": auth_token}
    )
    task_run = client.post(url, **post_req_params)
    assert task_run.status_code == FORBIDDEN_STATUS_CODE
    assert bytes(FORBIDDEN_ERROR_CLASS, encoding="utf") in task_run.data
    # While we are on it, test if the unauth handler correctly returns json if we set the content-type
    post_req_params.update(
        headers={"Authorization": auth_token, "Content-Type": "application/json"}
    )
    task_run = client.post(url, **post_req_params)
    assert task_run.status_code == FORBIDDEN_STATUS_CODE
    assert task_run.json["status"] == FORBIDDEN_ERROR_STATUS


def test_api_task_run_get_no_token(client):
    task_run = get_task_run(client, "task-B", "NOAUTH")
    assert task_run.status_code == UNAUTH_STATUS_CODE
    assert task_run.json["status"] == "ERROR"
    assert "Not authenticated" in task_run.json["reason"]


def test_api_task_run_get_bad_token(client):
    task_run = get_task_run(client, "task-B", "bad-token")
    assert task_run.status_code == FORBIDDEN_STATUS_CODE
    assert task_run.json["status"] == "ERROR"
    assert "Not authorized" in task_run.json["reason"]


def test_api_task_run_get_no_name(client):
    task_run = get_task_run(client, "")
    assert task_run.status_code == 400
    assert task_run.json["status"] == "ERROR"
    assert task_run.json["reason"] == "No task name given."


def test_api_task_run_get_nonexistent_task(client):
    task_run = get_task_run(client, "task-Z")
    assert task_run.status_code == 404
    assert task_run.json["status"] == "ERROR"
    assert "has no last run time" in task_run.json["reason"]


def test_api_task_run_post_no_name(client):
    task_run = post_task_run(client, "")
    assert task_run.status_code == 400
    assert task_run.json["status"] == "ERROR"
    assert task_run.json["reason"] == "No task name given."


def test_api_task_run_get_recent_entry(client):
    task_run = get_task_run(client, "task-B")
    assert task_run.status_code == 200
    assert task_run.json["frequency"] == 10
    assert task_run.json["process"] == "FlexMeasures"
    assert task_run.json["server"] == "test"
    task_time = isodate.parse_datetime(task_run.json.get("lastrun"))
    utcnow = datetime.utcnow().replace(tzinfo=pytz.utc)
    assert task_time <= utcnow
    assert task_time >= utcnow - timedelta(minutes=2)
    assert task_run.json.get("status") == "ERROR"


def test_api_task_run_get_older_entry_then_update(client):
    task_run = get_task_run(client, "task-A")
    assert task_run.status_code == 200
    task_time = isodate.parse_datetime(task_run.json.get("lastrun"))
    utcnow = datetime.utcnow().replace(tzinfo=pytz.utc)
    assert task_time <= utcnow - timedelta(days=1)
    assert task_time >= utcnow - timedelta(days=1, minutes=1)
    assert task_run.json.get("status") == "OK"
    # update the latest run of this task (also report that it failed)
    task_update = post_task_run(client, "task-A", False)
    assert task_update.status_code == 200
    task_run = get_task_run(client, "task-A")
    task_time = isodate.parse_datetime(task_run.json.get("lastrun"))
    utcnow = datetime.utcnow().replace(tzinfo=pytz.utc)
    assert task_time <= utcnow
    assert task_time >= utcnow - timedelta(minutes=1)
    assert task_run.json.get("status") == "ERROR"
