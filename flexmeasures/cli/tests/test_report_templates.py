"""Tests for the prepared report templates and their CLI integration."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import yaml

from sqlalchemy import select, update

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.reporting.aggregator import AggregatorReporter
from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.automations import prepare_report_parameters
from flexmeasures.data.services.report_templates import (
    PLACEHOLDER,
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


def test_energy_costs_template_validates(app, fresh_db, setup_dummy_asset_fresh_db):
    """The energy-costs template validates against the ProfitOrLossReporter schemas, once sensors are filled in."""
    template = get_report_template("energy-costs")
    assert template["reporter"] == "ProfitOrLossReporter"

    asset = fresh_db.session.get(GenericAsset, setup_dummy_asset_fresh_db)
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
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *", "UTC")
    reporter_class._parameters_schema.load(prepared_parameters)


def test_self_consumption_template_validates(app, fresh_db, setup_dummy_data_fresh_db):
    """The self-consumption template validates against the PandasReporter schemas, once sensors are filled in."""
    template = get_report_template("self-consumption")
    assert template["reporter"] == "PandasReporter"

    reporter_class = app.data_generators["reporter"][template["reporter"]]

    # the config is complete and valid as-is (sensors only enter through the parameters)
    assert find_placeholders(template["config"]) == []
    reporter_class._config_schema.load(template["config"])

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data_fresh_db
    parameters = _fill_sensors(
        template["parameters"], [sensor1_id, sensor2_id], [report_sensor_id]
    )
    assert find_placeholders(parameters) == []
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *", "UTC")
    reporter_class._parameters_schema.load(prepared_parameters)


def test_every_template_is_well_formed(app):
    """Every packaged template names a known reporter, and recommends a rolling window."""
    templates = list_report_templates()
    assert len(templates) == len(set(template["name"] for template in templates))

    for template in templates:
        for field in ("name", "description", "reporter", "config", "parameters"):
            assert field in template, f"{template.get('name')} misses {field}"
        assert template["reporter"] in app.data_generators["reporter"]
        # a rolling window, rather than a fixed period, is what suits a recurring report
        parameters = template["parameters"]
        assert "start" not in parameters and "end" not in parameters
        assert parameters["start-offset"] and parameters["end-offset"]
        # each template leaves its sensors, and only its sensors, to the user
        for description in parameters["input"] + parameters["output"]:
            assert description["sensor"] == PLACEHOLDER


def test_aggregate_sensors_template_validates(app, fresh_db, setup_dummy_data_fresh_db):
    """The aggregate-sensors template validates against the AggregatorReporter schemas, once sensors are filled in."""
    template = get_report_template("aggregate-sensors")
    assert template["reporter"] == "AggregatorReporter"

    reporter_class = app.data_generators["reporter"][template["reporter"]]

    # the config is complete and valid as-is (sensors only enter through the parameters)
    assert find_placeholders(template["config"]) == []
    reporter_class._config_schema.load(template["config"])

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data_fresh_db
    parameters = _fill_sensors(
        template["parameters"], [sensor1_id, sensor2_id], [report_sensor_id]
    )
    assert find_placeholders(parameters) == []
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *", "UTC")
    reporter_class._parameters_schema.load(prepared_parameters)


def test_aggregate_sensors_sums_its_input_sensors(
    app, fresh_db, setup_dummy_data_fresh_db
):
    """The aggregate-sensors template totals its input sensors event by event, at the resolution of the output sensor."""
    sensor1_id, sensor2_id, _, _ = setup_dummy_data_fresh_db
    sensor1 = fresh_db.session.get(Sensor, sensor1_id)
    site_sensor = Sensor(
        "site consumption",
        generic_asset=sensor1.generic_asset,
        event_resolution=timedelta(hours=1),
    )
    fresh_db.session.add(site_sensor)
    fresh_db.session.commit()

    template = get_report_template("aggregate-sensors")
    parameters = {
        "input": [
            {"name": "part-1", "sensor": sensor1_id},
            {"name": "part-2", "sensor": sensor2_id},
        ],
        "output": [{"sensor": site_sensor.id}],
        "start": "2023-04-10T00:00:00+00:00",
        "end": "2023-04-10T04:00:00+00:00",
    }
    report = AggregatorReporter(config=template["config"]).compute(
        parameters=parameters
    )[0]["data"]

    # both sensors hold the hour index as their value, so the site total is twice that
    assert len(report) == 4
    assert (report.values.T == [0, 2, 4, 6]).all()

    # weighing one input -1 subtracts it, which leaves nothing of two equal sensors
    config = dict(template["config"], weights={"part-2": -1.0})
    report = AggregatorReporter(config=config).compute(parameters=parameters)[0]["data"]
    assert (report.values.T == [0, 0, 0, 0]).all()


def test_daily_energy_template_totals_a_power_sensor(
    app, fresh_db, setup_dummy_asset_fresh_db
):
    """The daily-energy template converts power to energy and totals it per day."""
    template = get_report_template("daily-energy")
    assert template["reporter"] == "PandasReporter"

    reporter_class = app.data_generators["reporter"][template["reporter"]]
    assert find_placeholders(template["config"]) == []
    reporter_class._config_schema.load(template["config"])

    asset = fresh_db.session.get(GenericAsset, setup_dummy_asset_fresh_db)
    power_sensor = Sensor(
        "power", generic_asset=asset, event_resolution=timedelta(hours=1), unit="kW"
    )
    daily_sensor = Sensor(
        "daily energy",
        generic_asset=asset,
        event_resolution=timedelta(days=1),
        unit="MWh",
    )
    fresh_db.session.add_all([power_sensor, daily_sensor])
    source = DataSource("test source")
    fresh_db.session.add(source)
    fresh_db.session.flush()
    fresh_db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2023, 4, 10, tzinfo=timezone.utc)
                + timedelta(hours=t),
                belief_time=datetime(2023, 4, 9, tzinfo=timezone.utc),
                event_value=2,
                sensor=power_sensor,
                source=source,
            )
            for t in range(24)
        ]
    )
    fresh_db.session.commit()

    parameters = _fill_sensors(
        template["parameters"], [power_sensor.id], [daily_sensor.id]
    )
    assert find_placeholders(parameters) == []
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *", "UTC")
    reporter_class._parameters_schema.load(prepared_parameters)

    report = PandasReporter(config=template["config"]).compute(
        parameters={
            "input": parameters["input"],
            "output": parameters["output"],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-11T00:00:00+00:00",
        }
    )[0]["data"]

    # 2 kW for 24 hours is 48 kWh, recorded on a sensor that reports MWh
    assert len(report) == 1
    assert report.values[0, 0] == pytest.approx(0.048)


def test_clipped_values_template_bounds_its_input(
    app, fresh_db, setup_dummy_data_fresh_db
):
    """The clipped-values template pulls out-of-range values to the nearest bound."""
    template = get_report_template("clipped-values")
    assert template["reporter"] == "PandasReporter"

    # unlike the other templates, this one also leaves the range itself to the user
    assert find_placeholders(template["config"]) == [
        "transformations[0].kwargs.lower",
        "transformations[0].kwargs.upper",
    ]
    config = deepcopy(template["config"])
    config["transformations"][0]["kwargs"] = {"lower": 1, "upper": 2}
    app.data_generators["reporter"][template["reporter"]]._config_schema.load(config)

    sensor1_id, _, _, _ = setup_dummy_data_fresh_db
    sensor1 = fresh_db.session.get(Sensor, sensor1_id)
    clipped_sensor = Sensor(
        "clipped measurements",
        generic_asset=sensor1.generic_asset,
        event_resolution=timedelta(hours=1),
    )
    fresh_db.session.add(clipped_sensor)
    fresh_db.session.commit()

    report = PandasReporter(config=config).compute(
        parameters={
            "input": [{"name": "measurements", "sensor": sensor1_id}],
            "output": [{"name": "clipped", "sensor": clipped_sensor.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T04:00:00+00:00",
        }
    )[0]["data"]

    # the sensor holds the hour index (0, 1, 2, 3), clipped to the range [1, 2]
    assert len(report) == 4
    assert (report.values.T == [1, 1, 2, 2]).all()


def test_valid_range_template_leaves_out_values_outside_its_range(
    app, fresh_db, setup_dummy_data_fresh_db
):
    """The valid-range template drops out-of-range values, rather than pulling them to a bound."""
    template = get_report_template("valid-range")
    assert template["reporter"] == "PandasReporter"
    assert find_placeholders(template["config"]) == [
        "transformations[0].args[0]",
        "transformations[1].args[0]",
    ]
    config = deepcopy(template["config"])
    config["transformations"][0]["args"] = [1]
    config["transformations"][1]["args"] = [2]
    app.data_generators["reporter"][template["reporter"]]._config_schema.load(config)

    sensor1_id, _, _, _ = setup_dummy_data_fresh_db
    sensor1 = fresh_db.session.get(Sensor, sensor1_id)
    valid_sensor = Sensor(
        "valid measurements",
        generic_asset=sensor1.generic_asset,
        event_resolution=timedelta(hours=1),
    )
    fresh_db.session.add(valid_sensor)
    fresh_db.session.commit()

    report = PandasReporter(config=config).compute(
        parameters={
            "input": [{"name": "measurements", "sensor": sensor1_id}],
            "output": [{"name": "valid", "sensor": valid_sensor.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T04:00:00+00:00",
        }
    )[0]["data"]

    # the sensor holds the hour index (0, 1, 2, 3), of which only 1 and 2 lie in the range [1, 2]
    assert list(report.values.T[0]) == [1, 2]
    assert [t.hour for t in report.index.get_level_values("event_start")] == [1, 2]


def _save_values(db, sensor, start, values, resolution):
    """Record one belief per event on the sensor, known a day before the first event."""
    source = db.session.scalar(
        select(DataSource).filter_by(name="template test source")
    )
    if source is None:
        source = DataSource("template test source")
        db.session.add(source)
        db.session.flush()
    db.session.add_all(
        [
            TimedBelief(
                event_start=start + i * resolution,
                belief_time=start - timedelta(days=1),
                event_value=value,
                sensor=sensor,
                source=source,
            )
            for i, value in enumerate(values)
        ]
    )


def test_dynamic_tariff_template_adds_taxes_and_vat(
    app, fresh_db, setup_dummy_asset_fresh_db
):
    """The dynamic-tariff template adds the energy tax and the surcharge to the day-ahead price, and then the VAT, across resolutions."""
    template = get_report_template("dynamic-tariff")
    assert template["reporter"] == "PandasReporter"
    reporter_class = app.data_generators["reporter"][template["reporter"]]
    assert find_placeholders(template["config"]) == []
    reporter_class._config_schema.load(template["config"])

    asset = fresh_db.session.get(GenericAsset, setup_dummy_asset_fresh_db)
    quarter, day = timedelta(minutes=15), timedelta(days=1)
    day_ahead = Sensor(
        "day-ahead", generic_asset=asset, event_resolution=quarter, unit="EUR/MWh"
    )
    energy_tax = Sensor(
        "energy tax", generic_asset=asset, event_resolution=day, unit="EUR/MWh"
    )
    surcharge = Sensor(
        "surcharge", generic_asset=asset, event_resolution=day, unit="EUR/MWh"
    )
    vat = Sensor("VAT", generic_asset=asset, event_resolution=day, unit="%")
    tariff = Sensor(
        "tariff", generic_asset=asset, event_resolution=quarter, unit="EUR/MWh"
    )
    fresh_db.session.add_all([day_ahead, energy_tax, surcharge, vat, tariff])
    fresh_db.session.flush()
    start = datetime(2023, 4, 10, tzinfo=timezone.utc)
    _save_values(fresh_db, day_ahead, start, [100, 120, -20, 0], quarter)
    _save_values(fresh_db, energy_tax, start, [50], day)
    _save_values(fresh_db, surcharge, start, [10], day)
    _save_values(fresh_db, vat, start, [21], day)
    fresh_db.session.commit()

    parameters = _fill_sensors(
        template["parameters"],
        [day_ahead.id, energy_tax.id, surcharge.id, vat.id],
        [tariff.id],
    )
    assert find_placeholders(parameters) == []
    prepared_parameters = prepare_report_parameters(parameters, "0 14 * * *", "UTC")
    reporter_class._parameters_schema.load(prepared_parameters)

    report = PandasReporter(config=template["config"]).compute(
        parameters={
            "input": parameters["input"],
            "output": parameters["output"],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T01:00:00+00:00",
        }
    )[0]["data"]

    # (day-ahead + 50 + 10) * 1.21, also for a negative day-ahead price
    assert report.values.T[0] == pytest.approx([193.6, 217.8, 48.4, 72.6])


def test_meter_readings_to_flow_template_takes_the_difference_between_readings(
    app, fresh_db, setup_dummy_asset_fresh_db
):
    """Each flow is what the meter counted until its next reading, recorded at the interval's start, and implausible flows are left out."""
    template = get_report_template("meter-readings-to-flow")
    assert template["reporter"] == "PandasReporter"
    assert find_placeholders(template["config"]) == [
        "transformations[2].args[0]",
        "transformations[3].args[0]",
    ]
    config = deepcopy(template["config"])
    config["transformations"][2]["args"] = [0]
    config["transformations"][3]["args"] = [5]
    reporter_class = app.data_generators["reporter"][template["reporter"]]
    reporter_class._config_schema.load(config)

    asset = fresh_db.session.get(GenericAsset, setup_dummy_asset_fresh_db)
    quarter = timedelta(minutes=15)
    readings = Sensor(
        "meter readings", generic_asset=asset, event_resolution=quarter, unit="kWh"
    )
    flow = Sensor(
        "energy per interval", generic_asset=asset, event_resolution=quarter, unit="kWh"
    )
    fresh_db.session.add_all([readings, flow])
    fresh_db.session.flush()
    start = datetime(2023, 4, 10, tzinfo=timezone.utc)
    # the meter runs backwards once, between 00:30 and 00:45
    _save_values(fresh_db, readings, start, [10, 11, 13, 12, 14], quarter)
    fresh_db.session.commit()

    parameters = _fill_sensors(template["parameters"], [readings.id], [flow.id])
    prepared_parameters = prepare_report_parameters(parameters, "0 1 * * *", "UTC")
    reporter_class._parameters_schema.load(prepared_parameters)
    # the window ends one reading after midnight, so the day's last interval has the reading at its end
    assert prepared_parameters["end"].endswith("T00:15:00+00:00")

    report = PandasReporter(config=config).compute(
        parameters={
            "input": parameters["input"],
            "output": parameters["output"],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T01:15:00+00:00",
        }
    )[0]["data"]

    starts = [t.strftime("%H:%M") for t in report.index.get_level_values("event_start")]
    assert dict(zip(starts, report.values.T[0])) == {"00:00": 1, "00:15": 2, "00:45": 2}


def test_show_report_templates(app):
    """The show command lists all packaged templates, and prints a single template in full."""
    from flexmeasures.cli.data_show import show_report_templates

    runner = app.test_cli_runner()

    result = runner.invoke(show_report_templates)
    assert result.exit_code == 0, result.output
    for name, reporter in [
        ("aggregate-sensors", "AggregatorReporter"),
        ("clipped-values", "PandasReporter"),
        ("daily-energy", "PandasReporter"),
        ("dynamic-tariff", "PandasReporter"),
        ("energy-costs", "ProfitOrLossReporter"),
        ("meter-readings-to-flow", "PandasReporter"),
        ("self-consumption", "PandasReporter"),
        ("valid-range", "PandasReporter"),
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
    app, fresh_db, setup_dummy_data_fresh_db, clean_redis, tmp_path, freeze_server_now
):
    """A report automation created from the self-consumption template computes a working report."""
    from flexmeasures.cli.data_add import add_automation
    from flexmeasures.cli.jobs import run_automations
    from flexmeasures.utils.job_utils import work_on_rq

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data_fresh_db
    report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
    daily_sensor = Sensor(
        "daily self-consumption",
        generic_asset=report_sensor.generic_asset,
        event_resolution=timedelta(days=1),
    )
    fresh_db.session.add(daily_sensor)
    fresh_db.session.commit()
    daily_sensor_id = daily_sensor.id

    # Fill in the template's sensor placeholders, and widen its rolling window from one day to two,
    # which covers the dummy data once the clock is frozen at the start of the day after it.
    parameters = {
        "input": [
            dict(name="production", sensor=sensor1_id),
            dict(name="consumption", sensor=sensor2_id),
        ],
        "output": [dict(name="self-consumption", sensor=daily_sensor_id)],
        "start-offset": "-2D,DB",
        "end-offset": "DB",
    }
    freeze_server_now(datetime(2023, 4, 12, 0, 0, 30, tzinfo=timezone.utc))
    parameters_file = tmp_path / "parameters.yml"
    parameters_file.write_text(yaml.dump(parameters))

    runner = app.test_cli_runner()
    result = runner.invoke(
        add_automation,
        [
            "--asset", str(daily_sensor.generic_asset_id),
            "--name", "Daily self-consumption",
            "--cron", "* * * * *",  # due every minute
            "--type", "reporting",
            "--template", "self-consumption",
            "--parameters", str(parameters_file),
            "--timezone", "UTC",
        ],
    )  # fmt: skip
    assert "Successfully created" in result.output, result.output

    automation = fresh_db.session.execute(select(Automation)).scalar_one()
    assert automation.type == "reporting"
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
    assert automation.parameters["start-offset"] == "-2D,DB"
    assert automation.parameters["end-offset"] == "DB"

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


def test_report_template_placeholders_must_be_filled(
    app, fresh_db, setup_dummy_data_fresh_db
):
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
            "--type", "reporting",
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
            "--type", "reporting",
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


def test_report_template_cannot_be_combined_with_source(
    app, fresh_db, setup_dummy_data_fresh_db
):
    """A stored reporter source and a report template cannot both define the reporter configuration."""
    from flexmeasures.cli.data_add import add_automation, add_report

    source_id = fresh_db.session.execute(select(DataSource.id).limit(1)).scalar_one()
    runner = app.test_cli_runner()

    result = runner.invoke(
        add_report,
        ["--source", str(source_id), "--template", "self-consumption"],
    )
    assert result.exit_code != 0
    assert "--source cannot be combined with --template" in result.output

    result = runner.invoke(
        add_automation,
        [
            "--asset",
            "1",
            "--name",
            "Ambiguous report configuration",
            "--type",
            "reporting",
            "--source",
            str(source_id),
            "--template",
            "self-consumption",
        ],
    )
    assert result.exit_code != 0
    assert "--source cannot be combined with --template" in result.output


@pytest.mark.parametrize("option", ["--config", "--parameters"])
def test_add_report_template_rejects_non_mapping_override(
    app, fresh_db, tmp_path, option
):
    """Template override files must be mappings instead of producing an internal merge error."""
    from flexmeasures.cli.data_add import add_report

    override_file = tmp_path / "override.yaml"
    override_file.write_text("- not\n- a\n- mapping\n")

    result = app.test_cli_runner().invoke(
        add_report,
        ["--template", "self-consumption", option, str(override_file)],
    )

    assert result.exit_code != 0
    assert f"The {option} file must contain a YAML or JSON object" in result.output


def test_self_consumption_is_undefined_without_production(
    app, fresh_db, setup_dummy_data_fresh_db
):
    """The self-consumption ratio is missing when a reporting period has no production."""
    production_id, consumption_id, report_sensor_id, _ = setup_dummy_data_fresh_db
    report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
    daily_sensor = Sensor(
        "daily self-consumption with zero production",
        generic_asset=report_sensor.generic_asset,
        event_resolution=timedelta(days=1),
    )
    fresh_db.session.add(daily_sensor)
    fresh_db.session.execute(
        update(TimedBelief)
        .where(
            TimedBelief.sensor_id == production_id,
            TimedBelief.event_start < datetime(2023, 4, 11, tzinfo=timezone.utc),
        )
        .values(event_value=0)
    )
    fresh_db.session.commit()

    template = get_report_template("self-consumption")
    report = PandasReporter(config=template["config"]).compute(
        parameters={
            "input": [
                {"name": "production", "sensor": production_id},
                {"name": "consumption", "sensor": consumption_id},
            ],
            "output": [{"name": "self-consumption", "sensor": daily_sensor.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-12T00:00:00+00:00",
        }
    )[0]["data"]

    assert len(report) == 2
    assert pd.isna(report.values[0, 0])
    assert report.values[1, 0] == pytest.approx(1)
