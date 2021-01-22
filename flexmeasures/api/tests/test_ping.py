from flask import url_for


def test_ping_ok(client):
    pong = client.get(url_for("flexmeasures_api_ops.get_ping"))
    assert pong.status_code == 200
    assert pong.json["message"] == "ok"
