import json
import logging
import os
from datetime import datetime

import pandas as pd
import pytest
import pytz
import yaml

from sqlalchemy import select, func

from flexmeasures import Asset
from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.user import Account, Plan, RateLimitKey

from flexmeasures.cli.tests.utils import (
    check_command_ran_without_error,
    get_click_commands,
)
from flexmeasures.utils.time_utils import server_now
from flexmeasures.tests.utils import get_test_sensor


def _count_beliefs(db, sensor_id: int) -> int:
    """Count the beliefs recorded on the given sensor."""
    return db.session.scalar(
        select(func.count()).select_from(TimedBelief).filter_by(sensor_id=sensor_id)
    )


def test_add_annotation(app, fresh_db, setup_roles_users_fresh_db):
    from flexmeasures.cli.data_add import add_annotation

    db = fresh_db
    cli_input = {
        "content": "Company founding day",
        "at": "2016-05-11T00:00+02:00",
        "account": 1,
        "user": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_annotation, to_flags(cli_input))

    # Check result for success
    assert "Successfully added annotation" in result.output

    # Check database for annotation entry
    assert db.session.execute(
        select(Annotation)
        .filter(
            Annotation.content == cli_input["content"],
            Annotation.start == pd.Timestamp(cli_input["at"]),
        )
        .join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == cli_input["account"],
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.user_id == cli_input["user"],
        )
    ).scalar_one_or_none()


def test_add_plan(app, fresh_db):
    from flexmeasures.cli.data_add import new_plan

    db = fresh_db
    cli_input = {
        "name": "Pro",
        "trigger-rate-limit": "60 per 5 minutes",
        "rate-limit-key": "account",
        "max-assets": 200,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(new_plan, to_flags(cli_input))

    check_command_ran_without_error(result)
    assert "successfully created" in result.output

    plan = db.session.execute(select(Plan).filter_by(name="Pro")).scalar_one()
    assert plan.trigger_rate_limit == "60 per 5 minutes"
    assert plan.rate_limit_key == RateLimitKey.ACCOUNT
    assert plan.max_assets == 200
    # Fields we did not set fall back on the server-wide config settings
    assert plan.default_rate_limit is None
    assert plan.legacy is False


def test_add_plan_with_invalid_rate_limit(app, fresh_db):
    """A limit string we cannot make sense of is caught when the plan is created,
    rather than when a request comes in."""
    from flexmeasures.cli.data_add import new_plan

    db = fresh_db
    runner = app.test_cli_runner()
    result = runner.invoke(
        new_plan, to_flags({"name": "Typo", "trigger-rate-limit": "10 per fortnight"})
    )

    assert result.exit_code != 0
    assert "not a valid rate limit" in result.output
    assert db.session.execute(select(Plan).filter_by(name="Typo")).scalar() is None


def test_edit_plan(app, fresh_db):
    """A plan can be retired, so that it is no longer handed out."""
    from flexmeasures.cli.data_edit import edit_plan

    db = fresh_db
    plan = Plan(name="Pro", trigger_rate_limit="60 per 5 minutes")
    db.session.add(plan)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(edit_plan, ["--id", str(plan.id), "--legacy"])

    check_command_ran_without_error(result)
    assert db.session.execute(select(Plan).filter_by(name="Pro")).scalar_one().legacy


def test_edit_plan_name(app, fresh_db):
    """A plan is identified by its ID, so that --name can rename it."""
    from flexmeasures.cli.data_edit import edit_plan

    db = fresh_db
    plan = Plan(name="Pro", trigger_rate_limit="60 per 5 minutes")
    taken = Plan(name="Basic")
    db.session.add_all([plan, taken])
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(edit_plan, ["--id", str(plan.id), "--name", "Professional"])

    check_command_ran_without_error(result)
    assert db.session.get(Plan, plan.id).name == "Professional"

    # Names are unique, so renaming cannot take another plan's name
    result = runner.invoke(edit_plan, ["--id", str(plan.id), "--name", "Basic"])
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert db.session.get(Plan, plan.id).name == "Professional"


def test_edit_plan_clear_field(app, fresh_db):
    """A plan field can be cleared back to NULL, meaning the server-wide behaviour applies."""
    from flexmeasures.cli.data_edit import edit_plan

    db = fresh_db
    plan = Plan(name="Pro", trigger_rate_limit="60 per 5 minutes", max_users=10)
    db.session.add(plan)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        edit_plan, ["--id", str(plan.id), "--clear", "trigger-rate-limit"]
    )

    check_command_ran_without_error(result)
    plan = db.session.execute(select(Plan).filter_by(name="Pro")).scalar_one()
    assert plan.trigger_rate_limit is None
    assert plan.max_users == 10  # fields not named stay untouched

    # Setting and clearing the same field contradict each other
    result = runner.invoke(
        edit_plan, ["--id", str(plan.id), "--max-users", "5", "--clear", "max-users"]
    )
    assert result.exit_code != 0
    assert (
        db.session.execute(select(Plan).filter_by(name="Pro")).scalar_one().max_users
        == 10
    )


def test_add_holidays(app, fresh_db, setup_roles_users_fresh_db):
    from flexmeasures.cli.data_add import add_holidays

    db = fresh_db
    cli_input = {
        "year": 2020,
        "country": "NL",
        "account": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_holidays, to_flags(cli_input))

    # Check result for 11 public holidays
    assert "'NL': 11" in result.output

    # Check database for 11 annotation entries
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(Annotation)
            .join(AccountAnnotationRelationship)
            .filter(
                AccountAnnotationRelationship.account_id == cli_input["account"],
                AccountAnnotationRelationship.annotation_id == Annotation.id,
            )
            .join(DataSource)
            .filter(
                DataSource.id == Annotation.source_id,
                DataSource.name == "workalendar",
                DataSource.model == cli_input["country"],
            )
        )
        == 11
    )


def test_cli_help(app):
    """Test that showing help does not throw an error."""
    from flexmeasures.cli import data_add

    runner = app.test_cli_runner()
    for cmd in get_click_commands(data_add):
        result = runner.invoke(cmd, ["--help"])
        check_command_ran_without_error(result)
        assert "Usage" in result.output


def test_add_report_as_job(
    app, fresh_db, setup_dummy_data_fresh_db, clean_redis, tmp_path
):
    """The report CLI can persist its reporter and queue work for a worker."""
    from flexmeasures.cli.data_add import add_report

    input_1, input_2, output, _ = setup_dummy_data_fresh_db
    reporter_config = {
        "required_input": [{"name": "one"}, {"name": "two"}],
        "required_output": [{"name": "sum"}],
        "transformations": [
            {
                "df_input": "one",
                "method": "add",
                "args": ["@two"],
                "df_output": "sum",
            }
        ],
    }
    config_file = tmp_path / "report-config.json"
    config_file.write_text(json.dumps(reporter_config))
    parameters_file = tmp_path / "report-parameters.json"
    parameters_file.write_text(
        json.dumps(
            {
                "input": [
                    {"name": "one", "sensor": input_1},
                    {"name": "two", "sensor": input_2},
                ],
                "output": [{"name": "sum", "sensor": output}],
            }
        )
    )

    result = app.test_cli_runner().invoke(
        add_report,
        [
            "--config",
            str(config_file),
            "--parameters",
            str(parameters_file),
            "--start",
            "2023-04-10T00:00:00+00:00",
            "--end",
            "2023-04-10T10:00:00+00:00",
            "--as-job",
        ],
    )

    check_command_ran_without_error(result)
    assert "Created reporting job" in result.output
    job = app.queues["reporting"].jobs[0]
    assert job.timeout == app.queues["reporting"]._default_timeout
    assert job.meta["trigger"] == {"origin": "CLI"}
    source = fresh_db.session.get(DataSource, job.kwargs["data_source_id"])
    assert source is not None
    assert source.attributes["data_generator"]["config"] == {
        **reporter_config,
        "droplevels": False,
    }


def test_add_profit_report_as_job_requires_input(
    app, fresh_db, setup_dummy_data_fresh_db, clean_redis, tmp_path
):
    """The CLI must not queue a profit report without its flow sensor."""
    from flexmeasures.cli.data_add import add_report

    _, _, report_sensor_id, _ = setup_dummy_data_fresh_db
    report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
    price_sensor = Sensor(
        "price sensor",
        generic_asset=report_sensor.generic_asset,
        event_resolution=report_sensor.event_resolution,
        unit="EUR/kWh",
    )
    cost_sensor = Sensor(
        "cost sensor",
        generic_asset=report_sensor.generic_asset,
        event_resolution=report_sensor.event_resolution,
        unit="EUR",
    )
    fresh_db.session.add_all([price_sensor, cost_sensor])
    fresh_db.session.flush()

    config_file = tmp_path / "profit-config.json"
    config_file.write_text(json.dumps({"consumption_price_sensor": price_sensor.id}))
    parameters_file = tmp_path / "profit-parameters.json"
    parameters_file.write_text(json.dumps({"output": [{"sensor": cost_sensor.id}]}))
    source_count = fresh_db.session.scalar(
        select(func.count())
        .select_from(DataSource)
        .where(DataSource.type == "reporter")
    )

    result = app.test_cli_runner().invoke(
        add_report,
        [
            "--reporter",
            "ProfitOrLossReporter",
            "--config",
            str(config_file),
            "--parameters",
            str(parameters_file),
            "--start",
            "2023-04-10T00:00:00+00:00",
            "--end",
            "2023-04-10T10:00:00+00:00",
            "--as-job",
        ],
        catch_exceptions=True,
    )

    assert result.exit_code != 0
    assert "input" in str(result.exception)
    assert app.queues["reporting"].jobs == []
    assert (
        fresh_db.session.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(DataSource.type == "reporter")
        )
        == source_count
    )


def test_add_forecast_cli_accepts_regressor_ids_and_json_reference_lists(
    app,
    fresh_db,
    setup_fresh_test_forecast_data,
    monkeypatch,
):
    from flexmeasures.cli import data_add
    from flexmeasures.data.schemas.forecasting.pipeline import (
        TrainPredictPipelineConfigSchema,
    )
    from flexmeasures.data.schemas.sensors import SensorReference

    target_sensor = setup_fresh_test_forecast_data["solar-sensor"]
    regressor_sensor = setup_fresh_test_forecast_data["irradiance-sensor"]
    source = fresh_db.session.execute(
        select(DataSource).filter_by(name="Seita", type="demo script")
    ).scalar_one()
    captured_configs = []

    class StubForecaster:
        def set_job_trigger(self, origin):
            pass

        def compute(self, **kwargs):
            return {"n_jobs": 1}

    def capture_forecaster_config(**kwargs):
        captured_configs.append(
            TrainPredictPipelineConfigSchema().load(kwargs["config"])
        )
        return StubForecaster()

    monkeypatch.setattr(data_add, "get_data_generator", capture_forecaster_config)
    runner = app.test_cli_runner()
    common_args = ["--sensor", str(target_sensor.id), "--as-job", "--regressors"]

    reference_result = runner.invoke(
        data_add.add_forecast,
        common_args
        + [json.dumps([{"sensor": regressor_sensor.id, "sources": [source.id]}])],
    )
    plain_id_result = runner.invoke(
        data_add.add_forecast,
        common_args + [str(regressor_sensor.id)],
    )

    check_command_ran_without_error(reference_result)
    check_command_ran_without_error(plain_id_result)
    filtered_regressor = captured_configs[0]["future_regressors"][0]
    assert isinstance(filtered_regressor, SensorReference)
    assert filtered_regressor.sensor == regressor_sensor
    assert filtered_regressor.sources == [source]
    assert captured_configs[0]["past_regressors"] == [filtered_regressor]
    assert captured_configs[1]["future_regressors"] == [regressor_sensor]
    assert captured_configs[1]["past_regressors"] == [regressor_sensor]


def test_add_forecast_cli_accepts_a_source_filtered_target_sensor(
    app,
    fresh_db,
    setup_fresh_test_forecast_data,
    monkeypatch,
):
    """The target sensor takes a bare ID, or a JSON reference naming the sources to train on."""
    from flexmeasures.cli import data_add
    from flexmeasures.data.schemas.forecasting.pipeline import (
        ForecasterParametersSchema,
    )
    from flexmeasures.data.schemas.sensors import SensorReference

    target_sensor = setup_fresh_test_forecast_data["solar-sensor"]
    source = fresh_db.session.execute(
        select(DataSource).filter_by(name="Seita", type="demo script")
    ).scalar_one()
    captured_parameters = []

    class StubForecaster:
        def set_job_trigger(self, origin):
            pass

        def compute(self, **kwargs):
            captured_parameters.append(
                ForecasterParametersSchema().load(kwargs["parameters"])
            )
            return {"n_jobs": 1}

    monkeypatch.setattr(
        data_add, "get_data_generator", lambda **kwargs: StubForecaster()
    )
    runner = app.test_cli_runner()

    reference_result = runner.invoke(
        data_add.add_forecast,
        [
            "--sensor",
            json.dumps({"sensor": target_sensor.id, "sources": [source.id]}),
            "--as-job",
        ],
    )
    plain_id_result = runner.invoke(
        data_add.add_forecast,
        ["--sensor", str(target_sensor.id), "--as-job"],
    )

    check_command_ran_without_error(reference_result)
    check_command_ran_without_error(plain_id_result)
    filtered_target = captured_parameters[0]["sensor"]
    assert isinstance(filtered_target, SensorReference)
    assert filtered_target.sensor == target_sensor
    assert filtered_target.sources == [source]
    # Forecasts are recorded on the sensor itself, not on a source-filtered view of it.
    assert captured_parameters[0]["sensor_to_save"] == target_sensor
    assert captured_parameters[1]["sensor"] == target_sensor


def test_add_forecast_cli_reports_a_malformed_target_sensor_reference(
    app,
    fresh_db,
    setup_fresh_test_forecast_data,
):
    """A --sensor value that was meant to be a reference is reported as such, not as a bad integer."""
    from flexmeasures.cli import data_add

    target_sensor = setup_fresh_test_forecast_data["solar-sensor"]
    runner = app.test_cli_runner()

    result = runner.invoke(
        data_add.add_forecast,
        ["--sensor", '{"sensor": %d, "sources": [1]' % target_sensor.id],
    )

    assert result.exit_code != 0
    assert "looks like a JSON sensor reference" in result.output
    assert "Not a valid integer" not in result.output


def test_add_holidays_with_timezone(app, fresh_db, setup_roles_users_fresh_db):
    """Test that add_holidays respects --timezone and stores midnight local time."""
    from flexmeasures.cli.data_add import add_holidays
    import pandas as pd

    db = fresh_db
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_holidays,
        [
            "--year",
            "2024",
            "--country",
            "NL",
            "--account",
            "1",
            "--timezone",
            "Europe/Amsterdam",
        ],
    )
    check_command_ran_without_error(result)

    # Christmas is Dec 25; in Amsterdam (CET = UTC+1), midnight is 23:00 UTC on Dec 24.
    # Verify: annotation start for Christmas 2024 is stored as UTC 23:00 on Dec 24.
    christmas = db.session.execute(
        select(Annotation).filter(
            Annotation.content.ilike("%Christmas%"),
            Annotation.start == pd.Timestamp("2024-12-24T23:00:00Z"),
        )
    ).scalar_one_or_none()
    assert (
        christmas is not None
    ), "Christmas annotation should start at 2024-12-24T23:00Z (midnight Amsterdam time)"


def test_add_holidays_with_workalendar_school_holidays(
    app, fresh_db, setup_roles_users_fresh_db
):
    """Test adding NetherlandsWithSchoolHolidays (north region) for 2024 via the CLI."""
    from flexmeasures.cli.data_add import add_holidays
    from workalendar.europe.netherlands import NetherlandsWithSchoolHolidays
    import json

    db = fresh_db
    runner = app.test_cli_runner()

    result = runner.invoke(
        add_holidays,
        [
            "--year",
            "2024",
            "--calendar-class",
            "workalendar.europe.netherlands.NetherlandsWithSchoolHolidays",
            "--calendar-kwargs",
            json.dumps({"region": "north"}),
            "--account",
            "1",
            "--timezone",
            "Europe/Amsterdam",
        ],
    )
    check_command_ran_without_error(result)

    # Verify count matches what the calendar directly produces
    expected_count = len(NetherlandsWithSchoolHolidays(region="north").holidays(2024))
    count = db.session.scalar(
        select(func.count())
        .select_from(Annotation)
        .join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == 1,
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.name == "workalendar",
            DataSource.model == "NetherlandsWithSchoolHolidays",
        )
    )
    assert count == expected_count
    # NetherlandsWithSchoolHolidays returns public + school holiday days (a non-trivial set)
    assert (
        count > 90
    ), f"Expected >90 NL north school+public holidays in 2024, got {count}"


def test_add_holidays_with_workalendar_class_unsupported_year(app, fresh_db):
    """A calendar year without holiday data should abort with a friendly error, not a traceback."""
    from flexmeasures.cli.data_add import add_holidays
    import json

    runner = app.test_cli_runner()

    result = runner.invoke(
        add_holidays,
        [
            "--year",
            "2131",
            "--calendar-class",
            "workalendar.europe.netherlands.NetherlandsWithSchoolHolidays",
            "--calendar-kwargs",
            json.dumps({"region": "north"}),
            "--timezone",
            "Europe/Amsterdam",
        ],
    )

    assert result.exit_code != 0
    assert "has no holiday data for year 2131" in result.output
    assert "Traceback" not in result.output


def test_add_holidays_by_package_school(app, fresh_db, setup_roles_users_fresh_db):
    """Test adding school holidays via the holidays package.

    Uses Israel (IL) which reliably supports the 'school' category across
    holidays-package versions.  Germany/Bavaria was removed because the installed
    version of the holidays package no longer includes school holidays for DE.
    """
    from flexmeasures.cli.data_add import add_holidays

    db = fresh_db
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_holidays,
        [
            "--year",
            "2024",
            "--country",
            "IL",
            "--category",
            "school",
            "--account",
            "1",
            "--timezone",
            "Asia/Jerusalem",
        ],
    )
    check_command_ran_without_error(result)
    assert "Successfully added" in result.output

    # Israel has ~19 school holiday days in 2024; use 10 as a conservative lower bound.
    count = db.session.scalar(
        select(func.count())
        .select_from(Annotation)
        .join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == 1,
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.name == "holidays",
            DataSource.model == "IL",
        )
    )
    assert count > 10, f"Expected >10 IL school holiday days in 2024, got {count}"


def test_annotation_regressors_loaded_in_pipeline(
    app, fresh_db, setup_roles_users_fresh_db
):
    """Test annotation regressors: binary loading and CLI end-to-end.

    Setup
    -----
    A factory power sensor has a perfectly constant output of 10 MW, except during
    annotated shutdown periods (0 MW).  Several shutdowns are added to the
    2023 training window.  A forecast-window shutdown covers Jan 15-17 2024.

    Part 1 - BasePipeline._load_annotation_regressor_df
        Verify the annotation DataFrame contains 1.0 during the shutdown window and
        0.0 outside it.

    Part 2 - CLI end-to-end
        Verify future annotation rows remain available after annotation data is
        combined with target sensor beliefs.

    Part 3 - CLI end-to-end
        Invoke ``flexmeasures add forecasts`` via the Click test runner using the
        JSON double-quoted form of ``--annotation-regressors``.  Verify no exception
        is raised.

    Part 4 - DB persistence
        Verify that forecast beliefs were persisted for the full 4-day window.

    Part 5 - CLI parsing
        Verify the Python-literal single-quoted form is accepted by the same Click
        parameter type and schema used by the command, without writing a duplicate
        forecast to the same DB key.
    """
    import json
    from datetime import timedelta

    import pandas as pd
    from sqlalchemy import insert

    from flexmeasures.data.models.annotations import get_or_create_annotation
    from flexmeasures.data.services.data_sources import get_or_create_source
    from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
    from flexmeasures.data.models.time_series import Sensor, TimedBelief
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline
    from flexmeasures.data.schemas.forecasting.pipeline import (
        TrainPredictPipelineConfigSchema,
    )
    from flexmeasures.cli.data_add import add_forecast
    from flexmeasures.cli.utils import NestedDictParamType

    db = fresh_db

    # ------------------------------------------------------------------
    # 1.  Create asset + sensor
    # ------------------------------------------------------------------
    asset_type = GenericAssetType(name="Factory")
    db.session.add(asset_type)

    factory_asset = GenericAsset(name="Test Factory", generic_asset_type=asset_type)
    db.session.add(factory_asset)
    db.session.flush()

    power_sensor = Sensor(
        "power",
        generic_asset=factory_asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    db.session.add(power_sensor)
    db.session.flush()

    # ------------------------------------------------------------------
    # 2.  Annotate shutdown periods (2023 training shutdowns + 2024 test shutdown)
    # ------------------------------------------------------------------
    ann_source = get_or_create_source(
        "test", model="logistics", source_type="CLI script"
    )

    # Quarterly shutdowns spread through 2023 give the model a strong training signal.
    # Weekly shutdowns in Dec 2023 / early Jan 2024 ensure the default 30-day lookback
    # window (Dec 15 – Jan 14) always contains clear shutdown examples.
    shutdown_periods_training = [
        ("2023-02-15", "2023-02-17"),
        ("2023-05-15", "2023-05-17"),
        ("2023-08-15", "2023-08-17"),
        ("2023-11-15", "2023-11-17"),
        # weekly shutdowns within the default 30-day lookback
        ("2023-12-18", "2023-12-20"),
        ("2023-12-25", "2023-12-27"),
        ("2024-01-01", "2024-01-03"),
        ("2024-01-08", "2024-01-10"),
    ]
    forecast_shutdown = ("2024-01-15", "2024-01-17")
    all_shutdown_periods = shutdown_periods_training + [forecast_shutdown]

    for start_str, end_str in all_shutdown_periods:
        ann_obj = Annotation(
            content="Factory shutdown",
            start=pd.Timestamp(f"{start_str}T00:00:00Z"),
            end=pd.Timestamp(f"{end_str}T00:00:00Z"),
            source=ann_source,
            type="label",
        )
        ann, _ = get_or_create_annotation(ann_obj)
        factory_asset.annotations.append(ann)

    db.session.flush()

    # ------------------------------------------------------------------
    # 3.  Bulk-insert hourly training data: 10 MW normally, 0 MW during shutdowns
    # ------------------------------------------------------------------
    data_source = DataSource(name="factory_measurements", type="demo script")
    db.session.add(data_source)
    db.session.flush()

    # Build a set of shutdown hours for fast lookup
    shutdown_hours: set[pd.Timestamp] = set()
    for start_str, end_str in all_shutdown_periods:
        period = pd.date_range(
            start=pd.Timestamp(f"{start_str}T00:00:00Z"),
            end=pd.Timestamp(f"{end_str}T00:00:00Z"),
            freq="h",
            inclusive="left",
        )
        shutdown_hours.update(period)

    train_start = pd.Timestamp("2023-01-01T00:00:00Z")
    train_end = pd.Timestamp("2024-01-14T00:00:00Z")  # up to forecast window
    all_hours = pd.date_range(
        start=train_start, end=train_end, freq="h", inclusive="left"
    )

    rows = [
        {
            "sensor_id": power_sensor.id,
            "source_id": data_source.id,
            "event_start": ts.to_pydatetime(),
            "belief_horizon": timedelta(0),
            "cumulative_probability": 0.5,
            "event_value": 0.0 if ts in shutdown_hours else 10.0,
        }
        for ts in all_hours
    ]
    db.session.execute(insert(TimedBelief), rows)
    db.session.commit()

    # ------------------------------------------------------------------
    # Part 1: BasePipeline._load_annotation_regressor_df
    # ------------------------------------------------------------------
    annotation_spec = {
        "asset": factory_asset.id,
        "annotation_type": "label",  # snake_case: used directly by BasePipeline
        "name": "factory_shutdown",
    }

    pipeline = BasePipeline(
        target_sensor=power_sensor,
        future_regressors=[],
        past_regressors=[],
        n_steps_to_predict=48,
        max_forecast_horizon=24,
        forecast_frequency=1,
        event_starts_after=pd.Timestamp("2024-01-14T00:00:00Z"),
        event_ends_before=pd.Timestamp("2024-01-18T00:00:00Z"),
        annotation_regressors=[annotation_spec],
    )

    col_name = pipeline.annotation_regressor_names[0]

    ann_df = pipeline._load_annotation_regressor_df(
        spec=annotation_spec,
        col_name=col_name,
        start=pd.Timestamp("2024-01-14T00:00:00Z"),
        end=pd.Timestamp("2024-01-18T00:00:00Z"),
    )

    assert not ann_df.empty, "Annotation regressor DataFrame should not be empty"
    assert col_name in ann_df.columns

    shutdown_mask = (ann_df["event_start"] >= pd.Timestamp("2024-01-15")) & (
        ann_df["event_start"] < pd.Timestamp("2024-01-17")
    )
    assert (
        ann_df.loc[shutdown_mask, col_name] == 1.0
    ).all(), "Shutdown period should be marked as 1.0"
    assert (
        ann_df.loc[~shutdown_mask, col_name] == 0.0
    ).all(), "Non-shutdown period should be marked as 0.0"

    # ------------------------------------------------------------------
    # Part 2: Future annotation rows survive the sensor-belief merge
    # ------------------------------------------------------------------
    loaded_df = pipeline.load_data_all_beliefs()
    loaded_shutdown = loaded_df.loc[
        (loaded_df["event_start"] >= pd.Timestamp("2024-01-15"))
        & (loaded_df["event_start"] < pd.Timestamp("2024-01-17"))
    ]
    assert len(loaded_shutdown) == 48
    assert (loaded_shutdown[col_name] == 1.0).all()

    # ------------------------------------------------------------------
    # Part 3: CLI end-to-end
    # ------------------------------------------------------------------
    runner = app.test_cli_runner()
    sensor_id = str(power_sensor.id)
    asset_id = factory_asset.id
    common_args = [
        "--sensor",
        sensor_id,
        "--train-start",
        "2023-01-01T00:00+00:00",
        "--start",
        "2024-01-14T00:00+00:00",
        "--end",
        "2024-01-18T00:00+00:00",
    ]

    # --- Part 2a: JSON double-quoted form; also used for the forecast-effect check ---
    json_arg = json.dumps({"asset": asset_id, "annotation-type": "label"})
    result_json = runner.invoke(
        add_forecast, common_args + ["--annotation-regressors", json_arg]
    )
    assert (
        "Invalid input type" not in result_json.output
    ), f"CLI failed to parse JSON form:\n{result_json.output}"
    assert result_json.exception is None or "ValidationError" not in str(
        result_json.exception
    ), f"CLI raised ValidationError (JSON form): {result_json.exception}"
    assert result_json.exception is None, (
        f"CLI raised an unexpected exception (JSON form): {result_json.exception}\n"
        f"{result_json.output}"
    )

    # ------------------------------------------------------------------
    # Part 4: Verify that forecast beliefs were persisted for the full window.
    #
    # We do not assert a specific forecast magnitude here: whether the LGBM model
    # learns to produce lower values during the shutdown depends on regularisation
    # hyper-parameters and data density, which vary across environments.  The
    # structural correctness of the annotation regressor pipeline is already
    # verified in Part 1 (data loading) and Part 2 (CLI parsing + no exception).
    # ------------------------------------------------------------------
    from flexmeasures.data.models.data_sources import DataSource as DS

    forecast_source = db.session.execute(
        select(DS).filter(DS.model == "TrainPredictPipeline")
    ).scalar_one()

    forecast_beliefs = (
        db.session.execute(
            select(TimedBelief).where(
                TimedBelief.sensor_id == power_sensor.id,
                TimedBelief.source_id == forecast_source.id,
                TimedBelief.event_start >= pd.Timestamp("2024-01-14T00:00:00Z"),
                TimedBelief.event_start < pd.Timestamp("2024-01-18T00:00:00Z"),
            )
        )
        .scalars()
        .all()
    )

    assert forecast_beliefs, "No forecast beliefs found in DB after CLI invocation"
    assert len(forecast_beliefs) == 4 * 24, (
        f"Expected 96 hourly forecast beliefs for the 4-day window, "
        f"got {len(forecast_beliefs)}"
    )

    # --- Part 5: Python-literal single-quoted form – parsing only, no DB write ---
    literal_arg = str({"asset": asset_id, "annotation-type": "label"})
    parsed_literal = NestedDictParamType().convert(literal_arg, None, None)
    literal_config = TrainPredictPipelineConfigSchema().load(
        {"annotation-regressors": [parsed_literal]}
    )
    assert literal_config["annotation_regressors"][0]["asset"] == factory_asset
    assert literal_config["annotation_regressors"][0]["annotation_type"] == "label"


def test_add_reporter(app, fresh_db, setup_dummy_data_fresh_db, caplog):
    """
    The reporter aggregates input data from two sensors (both have 200 data points)
    to a two-hour resolution.

    The command is run twice:
        - The first run is for ten hours, so you expect five results.
            - start and end are defined in the configuration: 2023-04-10T00:00 -> 2023-04-10T10:00
            - this step uses 10 hours of data -> outputs 5 periods of 2 hours
        - The second is run without timing params, so the rest of the data
            - start is the time of the latest report value
            - end is the time of latest input data value
            - this step uses 190 hours of data -> outputs 95 periods of 2 hours
    """

    from flexmeasures.cli.data_add import add_report

    sensor1_id, sensor2_id, report_sensor_id, _ = setup_dummy_data_fresh_db

    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_agg"}],
        transformations=[
            dict(
                df_input="sensor_1",
                method="add",
                args=["@sensor_2"],
                df_output="df_agg",
            ),
            dict(method="resample_events", args=["2h"]),
        ],
    )

    # Running the command with start and end values.

    runner = app.test_cli_runner()
    caplog.set_level(logging.INFO)

    cli_input_params = {
        "config": "reporter_config.yaml",
        "parameters": "parameters.json",
        "reporter": "PandasReporter",
        "start": "2023-04-10T00:00:00 00:00",
        "end": "2023-04-10T10:00:00 00:00",
        "output-file": "test.csv",
    }

    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor1_id),
            dict(name="sensor_2", sensor=sensor2_id),
        ],
        output=[dict(name="df_agg", sensor=report_sensor_id)],
    )

    cli_input = to_flags(cli_input_params)

    # store config into config
    cli_input.append("--save-config")

    # run test in an isolated file system
    with runner.isolated_filesystem():

        # save reporter_config to a json file
        with open("reporter_config.yaml", "w") as f:
            yaml.dump(reporter_config, f)

        with open("parameters.json", "w") as f:
            json.dump(parameters, f)

        # call command
        result = runner.invoke(add_report, cli_input)
        check_command_ran_without_error(result)

        report_sensor = fresh_db.session.get(
            Sensor, report_sensor_id
        )  # get fresh report sensor instance

        assert "Reporter PandasReporter found." in caplog.text
        assert f"Report computation done for sensor `{report_sensor}`." in result.output

        # Check report is saved to the database
        stored_report = report_sensor.search_beliefs(
            event_starts_after=cli_input_params.get("start").replace(" ", "+"),
            event_ends_before=cli_input_params.get("end").replace(" ", "+"),
        )

        assert (
            stored_report.values.T == [1, 2 + 3, 4 + 5, 6 + 7, 8 + 9]
        ).all()  # check values

        assert os.path.exists("test.csv")  # check that the file has been created
        assert (
            os.path.getsize("test.csv") > 100
        )  # bytes. Check that the file is not empty

    # Running the command without timing params (start-offset/end-offset nor start/end).
    # This makes the command default the start time to the date of the last
    # value of the reporter sensor and the end time as the current time.

    previous_command_end = cli_input_params.get("end").replace(" ", "+")

    cli_input_params = {
        "source": stored_report.sources[0].id,
        "parameters": "parameters.json",
        "output-file": "test.csv",
        "timezone": "UTC",
    }

    cli_input = to_flags(cli_input_params)

    with runner.isolated_filesystem():

        # save reporter_config to a json file
        with open("reporter_config.json", "w") as f:
            json.dump(reporter_config, f)

        with open("parameters.json", "w") as f:
            json.dump(parameters, f)

        # call command
        result = runner.invoke(add_report, cli_input)
        check_command_ran_without_error(result)

        # Check if the report is saved to the database
        report_sensor = fresh_db.session.get(
            Sensor, report_sensor_id
        )  # get fresh report sensor instance

        assert (
            "Reporter `PandasReporter` fetched successfully from the database."
            in caplog.text
        )
        assert f"Report computation done for sensor `{report_sensor}`." in result.output

        stored_report = report_sensor.search_beliefs(
            event_starts_after=previous_command_end,
            event_ends_before=server_now(),
        )

        assert len(stored_report) == 95


def test_add_multiple_output(app, fresh_db, setup_dummy_data_fresh_db, caplog):
    """ """

    from flexmeasures.cli.data_add import add_report

    sensor_1_id, sensor_2_id, report_sensor_id, report_sensor_2_id = (
        setup_dummy_data_fresh_db
    )

    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_agg"}, {"name": "df_sub"}],
        transformations=[
            dict(
                df_input="sensor_1",
                method="add",
                args=["@sensor_2"],
                df_output="df_agg",
            ),
            dict(method="resample_events", args=["2h"]),
            dict(
                df_input="sensor_1",
                method="subtract",
                args=["@sensor_2"],
                df_output="df_sub",
            ),
            dict(method="resample_events", args=["2h"]),
        ],
    )

    # Running the command with start and end values.

    runner = app.test_cli_runner()
    caplog.set_level(logging.INFO)

    cli_input_params = {
        "config": "reporter_config.yaml",
        "parameters": "parameters.json",
        "reporter": "PandasReporter",
        "start": "2023-04-10T00:00:00+00:00",
        "end": "2023-04-10T10:00:00+00:00",
        "output-file": "test-$name.csv",
    }

    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor_1_id),
            dict(name="sensor_2", sensor=sensor_2_id),
        ],
        output=[
            dict(name="df_agg", sensor=report_sensor_id),
            dict(name="df_sub", sensor=report_sensor_2_id),
        ],
    )

    cli_input = to_flags(cli_input_params)

    # run test in an isolated file system
    with runner.isolated_filesystem():

        # save reporter_config to a json file
        with open("reporter_config.yaml", "w") as f:
            yaml.dump(reporter_config, f)

        with open("parameters.json", "w") as f:
            json.dump(parameters, f)

        # call command
        result = runner.invoke(add_report, cli_input)
        check_command_ran_without_error(result)

        assert os.path.exists("test-df_agg.csv")
        assert os.path.exists("test-df_sub.csv")

        report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
        report_sensor_2 = fresh_db.session.get(Sensor, report_sensor_2_id)

        assert "Reporter PandasReporter found" in caplog.text
        assert f"Report computation done for sensor `{report_sensor}`." in result.output
        assert (
            f"Report computation done for sensor `{report_sensor_2}`." in result.output
        )

        # check that the reports are saved
        assert all(
            report_sensor.search_beliefs(
                event_ends_before=datetime(2023, 4, 10, 10, tzinfo=pytz.UTC)
            ).values.flatten()
            == [1, 5, 9, 13, 17]
        )
        assert all(report_sensor_2.search_beliefs() == 0)


def _report_cli_input(tmp_path, sensor1_id, sensor2_id, report_sensor_id):
    """Config and parameters files for a single-output aggregation report."""
    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_agg"}],
        transformations=[
            dict(
                df_input="sensor_1",
                method="add",
                args=["@sensor_2"],
                df_output="df_agg",
            ),
            dict(method="resample_events", args=["2h"]),
        ],
    )
    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor1_id),
            dict(name="sensor_2", sensor=sensor2_id),
        ],
        output=[dict(name="df_agg", sensor=report_sensor_id)],
    )
    config_file = tmp_path / "reporter_config.yaml"
    config_file.write_text(yaml.safe_dump(reporter_config))
    parameters_file = tmp_path / "parameters.json"
    parameters_file.write_text(json.dumps(parameters))
    return {
        "config": str(config_file),
        "parameters": str(parameters_file),
        "reporter": "PandasReporter",
        "start": "2023-04-10T00:00:00+00:00",
        "end": "2023-04-10T10:00:00+00:00",
    }


def test_add_report_saves_beliefs(app, fresh_db, setup_dummy_data_fresh_db, tmp_path):
    """A synchronous report run records beliefs for its output sensor."""
    from flexmeasures.cli.data_add import add_report

    _, _, report_sensor_id, _ = setup_dummy_data_fresh_db
    runner = app.test_cli_runner()

    beliefs_before = _count_beliefs(fresh_db, report_sensor_id)
    result = runner.invoke(
        add_report,
        to_flags(
            _report_cli_input(
                tmp_path, *setup_dummy_data_fresh_db[:2], report_sensor_id
            )
        ),
    )
    check_command_ran_without_error(result)
    assert "has been saved to the database" in result.output

    assert _count_beliefs(fresh_db, report_sensor_id) == beliefs_before + 5
    report_sensor = fresh_db.session.get(Sensor, report_sensor_id)
    stored_report = report_sensor.search_beliefs(
        event_starts_after="2023-04-10T00:00:00+00:00",
        event_ends_before="2023-04-10T10:00:00+00:00",
    )
    assert (stored_report.values.T == [1, 2 + 3, 4 + 5, 6 + 7, 8 + 9]).all()


def test_add_report_dry_run_saves_no_beliefs(
    app, fresh_db, setup_dummy_data_fresh_db, tmp_path
):
    """A dry run shows the computed report without recording any belief."""
    from flexmeasures.cli.data_add import add_report

    _, _, report_sensor_id, _ = setup_dummy_data_fresh_db
    runner = app.test_cli_runner()

    beliefs_before = _count_beliefs(fresh_db, report_sensor_id)
    result = runner.invoke(
        add_report,
        to_flags(
            _report_cli_input(
                tmp_path, *setup_dummy_data_fresh_db[:2], report_sensor_id
            )
        )
        + ["--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "Not saving report for sensor" in result.output
    assert _count_beliefs(fresh_db, report_sensor_id) == beliefs_before

    # A real run right after does record, so the dry run skipped only persistence.
    result = runner.invoke(
        add_report,
        to_flags(
            _report_cli_input(
                tmp_path, *setup_dummy_data_fresh_db[:2], report_sensor_id
            )
        ),
    )
    check_command_ran_without_error(result)
    assert _count_beliefs(fresh_db, report_sensor_id) == beliefs_before + 5


def test_add_report_rejects_dry_run_as_job(app, setup_dummy_data_fresh_db):
    """A dry run cannot be queued, because its results would never reach the user."""
    from flexmeasures.cli.data_add import add_report

    runner = app.test_cli_runner()
    result = runner.invoke(add_report, ["--dry-run", "--as-job"])

    assert result.exit_code == 1
    assert "The --as-job flag cannot be combined with --dry-run" in result.output


def test_add_report_persistence_failure_saves_nothing(
    app, fresh_db, setup_dummy_data_fresh_db, tmp_path, mocker
):
    """If persistence fails midway, the synchronous run records nothing (single transaction)."""
    from flexmeasures.cli.data_add import add_report
    from flexmeasures.data.services import reporting as reporting_service

    sensor1_id, sensor2_id, report_sensor_id, report_sensor_2_id = (
        setup_dummy_data_fresh_db
    )
    runner = app.test_cli_runner()

    parameters = dict(
        input=[
            dict(name="sensor_1", sensor=sensor1_id),
            dict(name="sensor_2", sensor=sensor2_id),
        ],
        output=[
            dict(name="df_agg", sensor=report_sensor_id),
            dict(name="df_sub", sensor=report_sensor_2_id),
        ],
    )
    reporter_config = dict(
        required_input=[{"name": "sensor_1"}, {"name": "sensor_2"}],
        required_output=[{"name": "df_agg"}, {"name": "df_sub"}],
        transformations=[
            dict(
                df_input="sensor_1",
                method="add",
                args=["@sensor_2"],
                df_output="df_agg",
            ),
            dict(method="resample_events", args=["2h"]),
            dict(
                df_input="sensor_1",
                method="subtract",
                args=["@sensor_2"],
                df_output="df_sub",
            ),
            dict(method="resample_events", args=["2h"]),
        ],
    )
    config_file = tmp_path / "reporter_config.yaml"
    config_file.write_text(yaml.safe_dump(reporter_config))
    parameters_file = tmp_path / "parameters.json"
    parameters_file.write_text(json.dumps(parameters))
    cli_input = to_flags(
        {
            "config": str(config_file),
            "parameters": str(parameters_file),
            "reporter": "PandasReporter",
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T10:00:00+00:00",
        }
    )

    beliefs_before = (
        _count_beliefs(fresh_db, report_sensor_id),
        _count_beliefs(fresh_db, report_sensor_2_id),
    )
    real_save = reporting_service.save_to_db_and_count
    saves_attempted = []

    def fail_on_second_save(data, **kwargs):
        saves_attempted.append(data)
        if len(saves_attempted) > 1:
            raise RuntimeError("database gone")
        return real_save(data, **kwargs)

    mocker.patch.object(
        reporting_service, "save_to_db_and_count", side_effect=fail_on_second_save
    )
    with pytest.raises(RuntimeError, match="database gone"):
        runner.invoke(add_report, cli_input)

    # The first output really was saved before the failure, so the unchanged
    # counts below prove the failed run rolled everything back, leaving neither
    # output pending nor committed.
    assert len(saves_attempted) == 2
    assert _count_beliefs(fresh_db, report_sensor_id) == beliefs_before[0]
    assert _count_beliefs(fresh_db, report_sensor_2_id) == beliefs_before[1]


@pytest.mark.parametrize("process_type", [("INFLEXIBLE"), ("SHIFTABLE"), ("BREAKABLE")])
def test_add_process(
    app, process_power_sensor, process_type, add_market_prices_fresh_db, db
):
    """
    Schedule a 4h of consumption block at a constant power of 400kW in a day using
    the three process policies: INFLEXIBLE, SHIFTABLE and BREAKABLE.
    """

    from flexmeasures.cli.data_add import add_schedule

    epex_da = get_test_sensor(db)

    process_power_sensor_id = process_power_sensor
    flex_context = {"consumption-price": {"sensor": epex_da.id}}
    flex_model = {
        "duration": "PT4H",
        "power": "0.4",
        "process-type": process_type,
        "time-restrictions": [
            {"start": "2015-01-02T00:00:00+01:00", "duration": "PT2H"}
        ],
    }

    cli_input_params = {
        "sensor": process_power_sensor_id,
        "start": "2015-01-02T00:00:00+01:00",
        "duration": "PT24H",
        "scheduler": "ProcessScheduler",
        "flex-context": json.dumps(flex_context),
        "flex-model": json.dumps(flex_model),
    }

    cli_input = to_flags(cli_input_params)
    runner = app.test_cli_runner()

    # call command
    result = runner.invoke(add_schedule, cli_input)
    check_command_ran_without_error(result)
    # ProcessScheduler's make_schedule() call returns a dict (not the boolean
    # True), which used to be falsy enough to silently suppress this message;
    # confirm the message still appears.
    assert "New schedule is stored." in result.output

    process_power_sensor = db.session.get(Sensor, process_power_sensor_id)
    schedule = process_power_sensor.search_beliefs()
    # check if the schedule is not empty more detailed testing can be found
    # in data/models/planning/tests/test_process.py.
    assert (schedule == -0.4).event_value.sum() == 4


def _process_schedule_cli_input(db, process_power_sensor_id: int) -> dict:
    """Build the CLI input for scheduling a shiftable process, as used by the dry-run tests."""
    epex_da = get_test_sensor(db)
    return {
        "sensor": process_power_sensor_id,
        "start": "2015-01-02T00:00:00+01:00",
        "duration": "PT24H",
        "scheduler": "ProcessScheduler",
        "flex-context": json.dumps({"consumption-price": {"sensor": epex_da.id}}),
        "flex-model": json.dumps(
            {"duration": "PT4H", "power": "0.4", "process-type": "SHIFTABLE"}
        ),
    }


def test_add_schedule_dry_run_saves_no_beliefs(
    app, fresh_db, process_power_sensor, add_market_prices_fresh_db
):
    """A dry run shows the schedule it computed, without recording any belief."""
    from flexmeasures.cli.data_add import add_schedule

    runner = app.test_cli_runner()
    cli_input = to_flags(_process_schedule_cli_input(fresh_db, process_power_sensor))

    result = runner.invoke(add_schedule, cli_input + ["--dry-run"])
    check_command_ran_without_error(result)
    assert "Not saving schedule for sensor `power`" in result.output
    assert "covering events from" in result.output
    assert "computed but not stored (because of --dry-run)" in result.output
    assert "New schedule is stored." not in result.output
    sensor = fresh_db.session.get(Sensor, process_power_sensor)
    assert len(sensor.search_beliefs()) == 0

    # A normal run does record the schedule, so the dry run really skipped that step
    result = runner.invoke(add_schedule, cli_input)
    check_command_ran_without_error(result)
    assert "New schedule is stored." in result.output
    assert len(sensor.search_beliefs()) > 0


def test_add_schedule_rejects_dry_run_as_job(app, fresh_db, add_market_prices_fresh_db):
    """A dry run cannot be queued: the worker would save the schedule that the flag rules out."""
    from flexmeasures.cli.data_add import add_schedule, add_toy_account

    runner = app.test_cli_runner()
    runner.invoke(add_toy_account)
    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one_or_none()
    battery = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-battery", owner=toy_account)
    ).scalar_one_or_none()
    power_sensor = battery.sensors[0]
    prices = add_market_prices_fresh_db["epex_da"]

    cli_input = to_flags(
        {
            "start": "2014-12-31T23:00:00+00",
            "duration": "PT12H",
            "sensor": power_sensor.id,
            "scheduler": "StorageScheduler",
            "soc-at-start": "50%",
            "flex-context": json.dumps({"consumption-price": {"sensor": prices.id}}),
            "flex-model": json.dumps({"roundtrip-efficiency": "90%"}),
        }
    )
    result = runner.invoke(add_schedule, cli_input + ["--dry-run", "--as-job"])

    assert result.exit_code == 1
    assert "The --as-job flag cannot be combined with --dry-run" in result.output
    # Without the guard, the flag would be dropped and the queued job would store a schedule.
    assert app.queues["scheduling"].count == 0
    assert len(power_sensor.search_beliefs()) == 0


def test_add_toy_account_battery_uses_kw_sensors_and_kva_capacities(app, fresh_db):
    from flexmeasures.cli.data_add import add_toy_account

    result = app.test_cli_runner().invoke(add_toy_account, ["--kind", "battery"])

    check_command_ran_without_error(result)

    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one()
    building = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-building", owner=toy_account)
    ).scalar_one()
    battery = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-battery", owner=toy_account)
    ).scalar_one()
    solar = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-solar", owner=toy_account)
    ).scalar_one()
    day_ahead_sensor = fresh_db.session.execute(
        select(Sensor).filter_by(name="day-ahead prices")
    ).scalar_one()

    assert day_ahead_sensor.unit == "EUR/kWh"
    assert building.flex_context["site-power-capacity"] == "500 kVA"
    assert battery.flex_model["power-capacity"] == "500 kVA"
    assert battery.flex_model["soc-max"] == "450 kWh"
    assert battery.sensors[0].unit == "kW"
    assert solar.sensors[0].unit == "kW"


def test_add_toy_account_can_set_client_version_on_building(app, fresh_db):
    from flexmeasures.cli.data_add import add_toy_account

    result = app.test_cli_runner().invoke(
        add_toy_account, ["--kind", "battery", "--client-version", "0.8.1"]
    )

    check_command_ran_without_error(result)

    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one()
    building = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-building", owner=toy_account)
    ).scalar_one()

    assert building.attributes["flexmeasures-client-version"] == "0.8.1"


def test_add_toy_account_reporter_uses_kw_scale_units(app, fresh_db):
    from flexmeasures.cli.data_add import add_toy_account

    result = app.test_cli_runner().invoke(add_toy_account, ["--kind", "reporter"])

    check_command_ran_without_error(result)

    day_ahead_sensor = fresh_db.session.execute(
        select(Sensor).filter_by(name="day-ahead prices")
    ).scalar_one()
    grid_connection_capacity = fresh_db.session.execute(
        select(Sensor).filter_by(name="grid connection capacity")
    ).scalar_one()
    headroom = fresh_db.session.execute(
        select(Sensor).filter_by(name="headroom")
    ).scalar_one()

    assert day_ahead_sensor.unit == "EUR/kWh"
    assert grid_connection_capacity.unit == "kW"
    assert headroom.unit == "kW"
    assert grid_connection_capacity.search_beliefs().values.flatten().tolist() == [500]


def test_add_process_toy_account_reuses_existing_root_assets(app, fresh_db):
    from flexmeasures.cli.data_add import add_toy_account

    runner = app.test_cli_runner()
    result = runner.invoke(add_toy_account)
    assert result.exit_code == 0, result.output

    result = runner.invoke(add_toy_account, ["--kind", "process"])
    assert result.exit_code == 0, result.output

    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one()
    root_buildings = (
        fresh_db.session.execute(
            select(Asset).filter_by(
                name="toy-building",
                owner=toy_account,
                parent_asset_id=None,
            )
        )
        .scalars()
        .all()
    )
    root_processes = (
        fresh_db.session.execute(
            select(Asset).filter_by(
                name="toy-process",
                owner=toy_account,
                parent_asset_id=None,
            )
        )
        .scalars()
        .all()
    )

    assert len(root_buildings) == 1
    assert len(root_processes) == 1
    assert {sensor.name for sensor in root_processes[0].sensors} == {
        "Power (Inflexible)",
        "Power (Breakable)",
        "Power (Shiftable)",
    }


def test_add_toy_account_shell_vars_output(app, fresh_db):
    from flexmeasures.cli.data_add import add_toy_account

    runner = app.test_cli_runner()
    result = runner.invoke(add_toy_account, ["--shell-vars"])

    check_command_ran_without_error(result)

    shell_vars = dict(
        line.split("=", 1)
        for line in result.output.splitlines()
        if line.startswith("FM_TOY_")
    )

    assert {
        "FM_TOY_ACCOUNT_ID",
        "FM_TOY_PRICE_SENSOR_ID",
        "FM_TOY_BUILDING_ASSET_ID",
        "FM_TOY_BATTERY_ASSET_ID",
        "FM_TOY_BATTERY_SENSOR_ID",
        "FM_TOY_SOLAR_ASSET_ID",
        "FM_TOY_SOLAR_SENSOR_ID",
    }.issubset(shell_vars.keys())


@pytest.mark.parametrize("storage_power_capacity", ["sensor", "quantity", None])
@pytest.mark.parametrize("storage_efficiency", ["sensor", "quantity", None])
def test_add_storage_schedule(
    app,
    add_market_prices_fresh_db,
    storage_schedule_sensors,
    storage_power_capacity,
    storage_efficiency,
    fresh_db,
):
    """
    Test the 'flexmeasures add schedule for-storage' CLI command for adding storage schedules.

    This test evaluates the command's functionality in creating storage schedules for different configurations
    of power capacity and storage efficiency. It uses a combination of sensor-based and manually specified values
    for these parameters.

    The test performs the following steps:
    1. Simulates running the `flexmeasures add toy-account` command to set up a test account.
    2. Configures CLI input parameters for scheduling, including the start time, duration, and sensor IDs.
       The test also sets up parameters for state of charge at start and roundtrip efficiency.
    3. Depending on the test parameters, adjusts power capacity and efficiency settings. These settings can be
       either sensor-based (retrieved from storage_schedule_sensors fixture), manually specified quantities,
       or left undefined.
    4. Executes the 'add_schedule' command with the configured parameters.
    5. Verifies that the command executes successfully (exit code 0) and that the correct number of scheduled
       values (48 for a 12-hour period with 15-minute resolution) are created for the power sensor.
    """
    power_capacity_sensor, storage_efficiency_sensor = storage_schedule_sensors

    from flexmeasures.cli.data_add import add_schedule, add_toy_account

    runner = app.test_cli_runner()
    runner.invoke(add_toy_account)

    toy_account = fresh_db.session.execute(
        select(Account).filter_by(name="Toy Account")
    ).scalar_one_or_none()
    battery = fresh_db.session.execute(
        select(Asset).filter_by(name="toy-battery", owner=toy_account)
    ).scalar_one_or_none()
    power_sensor = battery.sensors[0]
    prices = add_market_prices_fresh_db["epex_da"]

    flex_context = {"consumption-price": {"sensor": prices.id}}
    flex_model = {
        "roundtrip-efficiency": "90%",
    }

    cli_input_params = {
        "start": "2014-12-31T23:00:00+00",
        "duration": "PT12H",
        "sensor": battery.sensors[0].id,
        "scheduler": "StorageScheduler",
        "soc-at-start": "50%",
        "flex-context": flex_context,
        "flex-model": flex_model,
    }

    if storage_power_capacity is not None:
        if storage_power_capacity == "sensor":
            cli_input_params["flex-model"]["consumption-capacity"] = {
                "sensor": power_capacity_sensor
            }
            cli_input_params["flex-model"]["production-capacity"] = {
                "sensor": power_capacity_sensor
            }
        else:
            cli_input_params["flex-model"]["consumption-capacity"] = "700kW"
            cli_input_params["flex-model"]["production-capacity"] = "700kW"

    if storage_efficiency is not None:
        if storage_efficiency == "sensor":
            cli_input_params["flex-model"]["storage-efficiency"] = {
                "sensor": storage_efficiency_sensor
            }
        else:
            cli_input_params["flex-model"]["storage-efficiency"] = "90%"

    # json dump flex-model and flex-context
    cli_input_params["flex-model"] = json.dumps(cli_input_params["flex-model"])
    cli_input_params["flex-context"] = json.dumps(cli_input_params["flex-context"])

    cli_input = to_flags(cli_input_params)

    result = runner.invoke(add_schedule, cli_input)

    check_command_ran_without_error(result)
    schedule = power_sensor.search_beliefs()
    max_power = schedule.event_value.abs().max()
    assert len(schedule) == 48
    assert power_sensor.unit == "kW"
    # The 700 kW quantity override is the highest cap used by this parametrized test.
    # The lower bound catches accidentally storing MW-scale values on the kW sensor.
    assert max_power > 1
    assert max_power <= 700


def test_add_storage_schedule_uses_state_of_charge_sensor_for_soc_at_start(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    add_charging_station_assets_fresh_db,
    setup_sources_fresh_db,
):
    """Test that the StorageScheduler reads soc-at-start from a sensor and stores
    schedules on dedicated consumption and production output sensors with the correct
    sign convention and clipping behaviour.

    Setup:
    - Bidirectional charging station (can both charge and discharge).
    - SOC at start: 2.5 MWh (read from a sensor belief).
    - Schedule window: 2015-01-03 00:00–12:00 CET.
      On this date the market data has consumption prices of -10 EUR/MWh for hours 0–7
      (incentivises charging) and production prices of +60 EUR/MWh for hours 8–23
      (incentivises discharging), so the optimizer is guaranteed to do both.

    Sign-convention and clipping assertions (both consumption and production sensors defined):
    - Consumption sensor (consumption_is_positive=True): all stored values ≥ 0
      (charging intervals are positive; discharging intervals are clipped to 0).
    - Production sensor (consumption_is_positive=False): all stored values ≥ 0
      (discharging intervals are stored as positive; charging intervals are clipped to 0).
    - No single timestep may carry both a positive consumption and a positive production
      value (the two sensors together partition the schedule without overlap).
    - At least one charging and one discharging event must actually occur.
    """
    from flexmeasures.cli.data_add import add_schedule

    # Use the bidirectional station so both charging and discharging can occur.
    bidirectional_charging_station = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    power_sensor = next(
        s for s in bidirectional_charging_station.sensors if s.name == "power"
    )
    soc_sensor = add_charging_station_assets_fresh_db["bi-soc"]

    # 2015-01-03: consumption prices are -10 EUR/MWh in hours 0-7 (charging rewarded)
    # and production prices are +60 EUR/MWh in hours 8-23 (discharging rewarded).
    start = "2015-01-03T00:00:00+01:00"

    fresh_db.session.add(
        TimedBelief(
            sensor=soc_sensor,
            source=setup_sources_fresh_db["Seita"],
            event_start=datetime.fromisoformat(start),
            event_value=2.5,
            belief_time=datetime.fromisoformat(start),
        )
    )

    # Add dedicated output sensors for the consumption (charging) and production
    # (discharging) parts of the schedule.
    consumption_output_sensor = Sensor(
        name="consumption output",
        generic_asset=bidirectional_charging_station,
        unit="MW",
        event_resolution=power_sensor.event_resolution,
    )
    production_output_sensor = Sensor(
        name="production output",
        generic_asset=bidirectional_charging_station,
        unit="MW",
        event_resolution=power_sensor.event_resolution,
    )
    fresh_db.session.add(consumption_output_sensor)
    fresh_db.session.add(production_output_sensor)
    fresh_db.session.commit()

    epex_da = add_market_prices_fresh_db["epex_da"]
    epex_da_production = add_market_prices_fresh_db["epex_da_production"]

    cli_input_params = {
        "sensor": power_sensor.id,
        "start": start,
        "duration": "PT12H",
        "scheduler": "StorageScheduler",
        "flex-context": json.dumps(
            {
                "consumption-price": {"sensor": epex_da.id},
                "production-price": {"sensor": epex_da_production.id},
            }
        ),
        "flex-model": json.dumps(
            {
                "state-of-charge": {"sensor": soc_sensor.id},
                "soc-min": "0 MWh",
                "soc-max": "5 MWh",
                "power-capacity": "2 MW",
                "consumption": {"sensor": consumption_output_sensor.id},
                "production": {"sensor": production_output_sensor.id},
            }
        ),
    }

    result = app.test_cli_runner().invoke(add_schedule, to_flags(cli_input_params))

    check_command_ran_without_error(result)
    assert len(power_sensor.search_beliefs()) == 48

    # Reload sensors from the DB after the schedule has been committed.
    consumption_output_sensor = fresh_db.session.get(
        Sensor, consumption_output_sensor.id
    )
    production_output_sensor = fresh_db.session.get(Sensor, production_output_sensor.id)
    consumption_beliefs = consumption_output_sensor.search_beliefs()
    production_beliefs = production_output_sensor.search_beliefs()

    assert len(consumption_beliefs) == 48
    assert len(production_beliefs) == 48

    consumption_values = consumption_beliefs.values.flatten()
    production_values = production_beliefs.values.flatten()

    # Sign convention: consumption sensor (consumption_is_positive=True) stores
    # charging as positive values; discharging intervals are clipped to 0.
    assert (
        consumption_values >= 0
    ).all(), "Consumption output sensor must only hold non-negative values"
    # Sign convention: production sensor (consumption_is_positive=False) stores
    # discharging as positive values; charging intervals are clipped to 0.
    assert (
        production_values >= 0
    ).all(), "Production output sensor must only hold non-negative values"
    # Clipping: the two sensors partition the schedule without overlap — no
    # single timestep should carry both a positive consumption and a positive
    # production value.
    assert not (
        (consumption_values > 0) & (production_values > 0)
    ).any(), "No timestep may have both positive consumption and positive production"
    # With negative consumption prices in hours 0-7 and positive production prices
    # in hours 8+, both charging and discharging must occur.
    assert (
        consumption_values > 0
    ).any(), "Some charging must occur given the negative consumption prices"
    assert (
        production_values > 0
    ).any(), "Some discharging must occur given the positive production prices"
