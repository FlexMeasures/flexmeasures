"""Tests for the report template endpoints (GET /api/v3_0/report-templates[/<name>])."""

from __future__ import annotations

import pytest
from flask import url_for

from flexmeasures.data.models.time_series import Sensor

# Tests here share one database, so the rows each test adds are deleted afterwards.
pytestmark = pytest.mark.usefixtures("undo_new_rows")


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 200),
        ("test_dummy_user_3@seita.nl", 200),  # templates are the same for every user
    ],
    indirect=["requesting_user"],
)
def test_list_report_templates_auth(
    app, setup_roles_users, requesting_user, expected_status_code
):
    with app.test_client() as client:
        response = client.get(url_for("ReportTemplateAPI:index"))
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_list_report_templates(app, setup_roles_users, requesting_user):
    """Every packaged template is listed, with its reporter, its skeletons and a description of each placeholder."""
    with app.test_client() as client:
        response = client.get(url_for("ReportTemplateAPI:index"))

    assert response.status_code == 200, response.json
    templates = {t["name"]: t for t in response.json["report-templates"]}
    assert sorted(templates) == [
        "building-consumption",
        "clipped-values",
        "daily-energy",
        "energy-costs",
        "self-consumption",
    ]
    self_consumption = templates["self-consumption"]
    assert self_consumption["reporter"] == "PandasReporter"
    assert self_consumption["parameters"]["start-offset"] == "-1D,DB"
    assert [
        (p["section"], p["kind"], p["label"]) for p in self_consumption["placeholders"]
    ] == [
        ("parameters", "sensor", "Input sensor: production"),
        ("parameters", "sensor", "Input sensor: consumption"),
        ("parameters", "sensor", "Output sensor: self-consumption"),
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_report_template(app, setup_roles_users, requesting_user):
    with app.test_client() as client:
        response = client.get(url_for("ReportTemplateAPI:get", name="clipped-values"))
        missing = client.get(url_for("ReportTemplateAPI:get", name="no-such-template"))

    assert response.status_code == 200, response.json
    assert response.json["name"] == "clipped-values"
    assert [p["kind"] for p in response.json["placeholders"]] == [
        "value",
        "value",
        "sensor",
        "sensor",
    ]
    assert missing.status_code == 404
    assert "no-such-template" in missing.json["message"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_report_automation_refuses_unfilled_template_placeholders(
    app, db, add_battery_assets, requesting_user
):
    """A report automation started from a template is refused while any placeholder is left, naming each one."""
    battery = add_battery_assets["Test battery"]
    clipped_sensor = Sensor(
        "clipped power",
        generic_asset=battery,
        event_resolution=battery.sensors[0].event_resolution,
        unit=battery.sensors[0].unit,
    )
    db.session.add(clipped_sensor)
    db.session.commit()

    with app.test_client() as client:
        template = client.get(
            url_for("ReportTemplateAPI:get", name="clipped-values")
        ).json
        parameters = dict(
            template["parameters"],
            input=[{"name": "measurements", "sensor": battery.sensors[0].id}],
            output=[{"name": "clipped", "sensor": clipped_sensor.id}],
        )
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Clipped power",
                "cron": "0 1 * * *",
                "type": "reporting",
                "data-generator": template["reporter"],
                "config": template["config"],
                "parameters": parameters,
            },
        )

    assert response.status_code == 422, response.json
    assert response.json["message"]["json"] == {
        "config": [
            "Replace the 'FILL_IN' template placeholder at transformations[0].kwargs.lower.",
            "Replace the 'FILL_IN' template placeholder at transformations[0].kwargs.upper.",
        ]
    }
