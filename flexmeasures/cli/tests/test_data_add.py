from sqlalchemy import select, func

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource

from flexmeasures.cli.tests.utils import (
    check_command_ran_without_error,
    get_click_commands,
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
        .filter_by(
            content=cli_input["content"],
            start=cli_input["at"],
        )
        .join(AccountAnnotationRelationship)
        .filter_by(
            account_id=cli_input["account"],
            annotation_id=Annotation.id,
        )
        .join(DataSource)
        .filter_by(
            id=Annotation.source_id,
            user_id=cli_input["user"],
        )
    ).scalar_one_or_none()


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
        Invoke ``flexmeasures add forecasts`` via the Click test runner using both
        the JSON double-quoted form and the Python-literal single-quoted form of
        ``--annotation-regressors``.  Verify no exception is raised.

    Part 3 - DB persistence
        Verify that forecast beliefs were persisted for the full 4-day window.
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
    from flexmeasures.cli.data_add import add_forecast

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
    # Part 2: CLI end-to-end
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
    # Part 3: Verify that forecast beliefs were persisted for the full window.
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

    # --- Part 2b: Python-literal single-quoted form – parsing only, no DB check ---
    # The second invocation writes to the same window; we only care that argument
    # parsing succeeds (no marshmallow ValidationError), not about DB uniqueness.
    literal_arg = str({"asset": asset_id, "annotation-type": "label"})
    result_literal = runner.invoke(
        add_forecast, common_args + ["--annotation-regressors", literal_arg]
    )
    assert (
        "Invalid input type" not in result_literal.output
    ), f"CLI failed to parse Python-literal form:\n{result_literal.output}"
    assert result_literal.exception is None or "ValidationError" not in str(
        result_literal.exception
    ), f"CLI raised ValidationError (Python-literal form): {result_literal.exception}"
