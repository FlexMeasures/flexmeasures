"""The task-check token: an empty one lets nobody in, and refusals do not reveal the server mode."""

import pytest
from flask import url_for


def check_task(client, headers):
    return client.get(
        url_for("flexmeasures_api_ops.get_task_run"),
        query_string={"name": "task-A"},
        headers=headers,
    )


@pytest.mark.parametrize("configured_token", ["", None])
def test_unset_task_check_token_accepts_no_header(
    app, client, monkeypatch, configured_token
):
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_TASK_CHECK_AUTH_TOKEN", configured_token
    )
    response = check_task(client, {"Authorization": ""})
    assert response.status_code == 403
    assert response.json["status"] == "ERROR"


def test_refusals_do_not_reveal_the_server_mode(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "FLEXMEASURES_MODE", "secret-mode")
    for headers in ({}, {"Authorization": "wrong-token"}):
        response = check_task(client, headers)
        assert response.status_code in (401, 403)
        assert "secret-mode" not in response.get_data(as_text=True)


def test_right_task_check_token_is_accepted(app, client, setup_api_test_data):
    response = check_task(
        client, {"Authorization": app.config["FLEXMEASURES_TASK_CHECK_AUTH_TOKEN"]}
    )
    assert response.status_code == 200
    assert response.json["server"] == app.config["FLEXMEASURES_MODE"]
