"""Tests for the prepared report templates and their CLI integration."""

from copy import deepcopy
from datetime import timedelta

import pytest
import yaml

from sqlalchemy import select

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.automations import prepare_report_parameters
from flexmeasures.data.services.report_templates import (
    find_placeholders,
    get_report_template,
    list_report_templates,
)


@pytest.fixture(scope="function")
def clean_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


def _fill_sensors(
    parameters: dict, input_sensor_ids: list[int], output_sensor_ids: list[int]
) -> dict:
    """Fill the sensor placeholders in a template's parameters skeleton."""
    parameters = deepcopy(parameters)
    for description, sensor_id in zip(parameters["input"], input_sensor_ids):
        description["sensor"] = sensor_id
    for description, sensor_id in zip(parameters["output"], output_sensor_ids):
        description["sensor"] = sensor_id
    return parameters


def test_energy_costs_template_validates(app, fresh_db, setup_dummy_asset):
    """The energy-costs template validates against the ProfitOrLossReporter schemas, once sensors are filled in."""
    template = get_report_template("energy-costs")
    assert template["reporter"] == "ProfitOrLossReporter"

    asset = fresh_db.session.get(GenericAsset, setup_dummy_asset)
    price_sensor = Sensor(
        "price",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
    )
    power_sensor = Sensor(
        "power", generic_asset=asset, event_resolution=timedelta(hours=1), unit="MW"
    )
    cost_sensor = Sensor(
        "costs", generic_asset=asset, event_resolution=timedelta(days=1), unit="EUR"
    )
    fresh_db.session.add_all([price_sensor, power_sensor, cost_sensor])
    fresh_db.session.flush()

    reporter_class = app.data_generators["reporter"][template["reporter"]]

    # the config loads cleanly, once the price sensor placeholder is filled in
    config = dict(template["config"], consumption_price_sensor=price_sensor.id)
    assert find_placeholders(config) == []
    reporter_class._config_schema.load(config)

    # the parameters skeleton loads cleanly, once the sensor placeholders are
    # filled in and the recommended rolling window is resolved
    parameters = _fill_sensors(
        template["parameters"], [power_sensor.id], [cost_sensor.id]
    )
    assert find_placeholders(parameters) == []
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *")
    reporter_class._parameters_schema.load(prepared_parameters)


def test_self_consumption_template_validates(app, fresh_db, setup_dummy_data):
    """The self-consumption template validates against the PandasReporter schemas, once sensors are filled in."""
    template = get_report_template("self-consumption")
    assert template["reporter"] == "PandasReporter"

    reporter_class = app.data_generators["reporter"][template["reporter"]]

    # the config is complete and valid as-is (sensors only enter through the parameters)
    assert find_placeholders(template["config"]) == []
    reporter_class._config_schema.load(template["config"])

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data
    parameters = _fill_sensors(
        template["parameters"], [sensor1_id, sensor2_id], [report_sensor_id]
    )
    assert find_placeholders(parameters) == []
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *")
    reporter_class._parameters_schema.load(prepared_parameters)


def test_show_report_templates(app):
    """The show command lists all packaged templates, and prints a single template in full."""
    from flexmeasures.cli.data_show import show_report_templates

    runner = app.test_cli_runner()

    result = runner.invoke(show_report_templates)
    assert result.exit_code == 0, result.output
    for name, reporter in [
        ("energy-costs", "ProfitOrLossReporter"),
        ("self-consumption", "PandasReporter"),
    ]:
        assert name in result.output
        assert reporter in result.output

    result = runner.invoke(show_report_templates, ["--name", "self-consumption"])
    assert result.exit_code == 0, result.output
    assert "PandasReporter" in result.output
    assert "FILL_IN" in result.output
    # the printed YAML can be piped to a file and loads cleanly
    assert yaml.safe_load(result.output)["name"] == "self-consumption"

    result = runner.invoke(show_report_templates, ["--name", "unknown"])
    assert result.exit_code != 0
    assert "Unknown report template" in result.output


def test_add_and_run_report_automation_with_template(
    app, fresh_db, setup_dummy_data, clean_redis, tmp_path
):
    """A report automation created from the self-consumption template computes a working report."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.utils.job_utils import work_on_rq

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data
    report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
    daily_sensor = Sensor(
        "daily self-consumption",
        generic_asset=report_sensor.generic_asset,
        event_resolution=timedelta(days=1),
    )
    fresh_db.session.add(daily_sensor)
    fresh_db.session.commit()
    daily_sensor_id = daily_sensor.id

    # Fill in the template's sensor placeholders, and use an absolute reporting window
    # (the dummy data lives in April 2023), replacing the template's rolling window
    parameters = dict(
        input=[
            dict(name="production", sensor=sensor1_id),
            dict(name="consumption", sensor=sensor2_id),
        ],
        output=[dict(name="self-consumption", sensor=daily_sensor_id)],
        start="2023-04-10T00:00:00+00:00",
        end="2023-04-12T00:00:00+00:00",
    )
    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text(yaml.dump(parameters))

    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Daily self-consumption",
            "--cron", "* * * * *",  # due every minute
            "--type", "reports",
            "--template", "self-consumption",
            "--parameters", str(parameters_file),
        ],
    )  # fmt: skip
    assert "Successfully created" in result.output, result.output

    automation = fresh_db.session.execute(select(Automation)).scalar_one()
    assert automation.type == "reports"
    assert automation.generator is not None
    assert automation.generator.model == "PandasReporter"
    # the reporter config came from the template
    template = get_report_template("self-consumption")
    stored_config = automation.generator.attributes["data_generator"]["config"]
    assert stored_config["required_input"] == template["config"]["required_input"]
    assert len(stored_config["transformations"]) == len(
        template["config"]["transformations"]
    )
    # user-provided timing fields replaced the template's rolling window
    assert "start-offset" not in automation.parameters
    assert "end-offset" not in automation.parameters
    assert automation.parameters["start"] == "2023-04-10T00:00:00+00:00"

    # run the automation and process the queued reporting job
    result = runner.invoke(run_automations)
    assert result.exit_code == 0, result.output
    assert "queued 1 reporting job(s)" in result.output, result.output
    work_on_rq(app.queues["reporting"])

    stored_report = fresh_db.session.get(Sensor, daily_sensor_id).search_beliefs(
        event_starts_after="2023-04-10T00:00:00+00:00",
        event_ends_before="2023-04-12T00:00:00+00:00",
    )
    # both sensors hold identical data, so all production is consumed on-site
    assert len(stored_report) == 2
    assert (stored_report.values.T == [1.0, 1.0]).all()


def test_report_template_placeholders_must_be_filled(app, fresh_db, setup_dummy_data):
    """Leaving template placeholders unfilled produces a clear validation error."""
    from flexmeasures.cli.data_add import add_automation, add_report

    runner = app.test_cli_runner()

    # add automation: unfilled sensor placeholders are rejected with a clear error
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Unfilled report",
            "--cron", "0 1 * * *",
            "--type", "reports",
            "--template", "self-consumption",
        ],
    )  # fmt: skip
    assert result.exit_code != 0
    assert "FILL_IN" in result.output
    assert "parameters: input[0].sensor" in result.output

    # add report: same
    result = runner.invoke(add_report, ["--template", "energy-costs"])
    assert result.exit_code != 0
    assert "FILL_IN" in result.output
    assert "config: consumption_price_sensor" in result.output

    # unknown templates are rejected, listing the available ones
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Unknown template",
            "--cron", "0 1 * * *",
            "--type", "reports",
            "--template", "unknown",
        ],
    )  # fmt: skip
    assert result.exit_code != 0
    assert "Unknown report template" in result.output
    for template in list_report_templates():
        assert template["name"] in result.output

    # templates are only supported for report automations
    result = runner.invoke(
        add_automation,
        [
            "--asset", "1",
            "--name", "Forecasts from a report template",
            "--cron", "0 1 * * *",
            "--template", "self-consumption",
        ],
    )  # fmt: skip
    assert result.exit_code != 0
    assert "only supported for report automations" in result.output
