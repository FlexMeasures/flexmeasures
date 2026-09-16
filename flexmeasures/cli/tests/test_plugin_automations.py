"""CLI payload validation and UI inspection for plugin-defined automations."""

from dataclasses import replace
import json

from flask_login import login_user, logout_user
import pytest
from sqlalchemy import select

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.user import User
from flexmeasures.data.tests.test_plugin_automations_fresh_db import (
    ingestion_assets as _ingestion_assets,
    ingestion_plugin as _ingestion_plugin,
    make_automation,
)
from flexmeasures.ui.views.assets.views import AssetCrudUI

ingestion_assets = _ingestion_assets
ingestion_plugin = _ingestion_plugin


def ingestion_cli_args(tmp_path, root, sensor, parameters):
    """Build an ingestion creation command with independent YAML payloads."""
    config_file = tmp_path / "config.yml"
    parameters_file = tmp_path / "parameters.yml"
    config_file.write_text(f"sensor: {sensor.id}\n")
    parameters_file.write_text(parameters)
    return [
        "--asset",
        str(root.id),
        "--name",
        "CLI site ingestion",
        "--type",
        "mock-ingestion",
        "--config",
        str(config_file),
        "--parameters",
        str(parameters_file),
    ]


def test_custom_cli_yaml_payloads(
    app, fresh_db, ingestion_plugin, ingestion_assets, tmp_path
):
    from flexmeasures.cli.data_add import add_automation

    root, sensors = ingestion_assets
    result = app.test_cli_runner().invoke(
        add_automation, ingestion_cli_args(tmp_path, root, sensors[0], "value: 12.5\n")
    )
    assert result.exit_code == 0, result.output
    assert "Successfully created" in result.output
    automation = fresh_db.session.scalar(select(Automation))
    assert automation.type == "mock-ingestion"
    assert automation.parameters == {"value": 12.5}
    assert automation.generator.model == "MockIngestionGenerator"
    assert automation.generator.attributes["data_generator"]["config"] == {
        "sensor": sensors[0].id
    }


@pytest.mark.parametrize(
    "parameters", ["unrecognized: true\n", "value: invalid\n", "dry-run: false\n"]
)
def test_custom_cli_rejects_invalid_parameters(
    app, fresh_db, ingestion_plugin, ingestion_assets, tmp_path, parameters
):
    from flexmeasures.cli.data_add import add_automation

    root, sensors = ingestion_assets
    result = app.test_cli_runner().invoke(
        add_automation, ingestion_cli_args(tmp_path, root, sensors[0], parameters)
    )
    assert result.exit_code != 0
    assert "Invalid measurement parameters" in result.output
    assert "Unknown field" in result.output or "Not a valid number" in result.output
    assert fresh_db.session.scalar(select(Automation)) is None


@pytest.mark.parametrize("available", [True, False])
def test_show_custom_automation_json(
    app, fresh_db, ingestion_plugin, ingestion_assets, available
):
    from flexmeasures.cli.data_show import list_automations

    root, sensors = ingestion_assets
    automation = make_automation(fresh_db, root, sensors[0], parameters={"value": 21.0})
    if not available:
        del app.automation_handlers["mock-ingestion"]
    result = app.test_cli_runner().invoke(
        list_automations, ["--asset", str(root.id), "--as-json"]
    )
    assert result.exit_code == 0, result.output
    records = json.loads(result.output)
    assert len(records) == 1
    record = records[0]
    assert record["id"] == automation.id
    assert record["type"] == "mock-ingestion"
    assert record["available"] is available
    assert record["parameters"] == {"value": 21.0}
    assert record["source"] == {
        "id": automation.generator_id,
        "model": "MockIngestionGenerator",
        "version": "1.0",
        "config": {"sensor": sensors[0].id},
    }


@pytest.mark.parametrize("available", [True, False])
def test_ui_inspects_custom_and_unavailable_type(
    app,
    fresh_db,
    ingestion_plugin,
    ingestion_assets,
    setup_roles_users_fresh_db,
    available,
):
    root, sensors = ingestion_assets
    user = fresh_db.session.get(User, setup_roles_users_fresh_db["Test Prosumer User"])
    root.owner = user.account
    fresh_db.session.commit()
    make_automation(fresh_db, root, sensors[0])
    if available:
        app.automation_handlers["mock-ingestion"] = replace(
            app.automation_handlers["mock-ingestion"],
            display_name='Measurements <script>alert("label")</script>',
        )
    else:
        del app.automation_handlers["mock-ingestion"]
    with app.test_request_context(f"/assets/{root.id}/automations"):
        login_user(user)
        try:
            response = AssetCrudUI().automations(str(root.id))
        finally:
            logout_user()
    assert 'id="automationsTable-mock-ingestion"' in response
    if available:
        assert "Measurements &lt;script&gt;" in response
        assert '<script>alert("label")</script>' not in response
        assert r"\u003cscript\u003e" in response
    else:
        assert "mock-ingestion (plugin unavailable)" in response
    assert "Create plugin-defined automation types with the CLI" in response
