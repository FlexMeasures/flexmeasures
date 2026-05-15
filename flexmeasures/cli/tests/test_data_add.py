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
    """Test adding NetherlandsWithSchoolHolidays (north region) for 2024 via workalendar."""
    from workalendar.europe.netherlands import NetherlandsWithSchoolHolidays
    from flexmeasures.data.services.data_sources import get_or_create_source
    from flexmeasures.data.models.annotations import get_or_create_annotation
    from flexmeasures.data.models.user import Account
    import pandas as pd

    db = fresh_db

    cal = NetherlandsWithSchoolHolidays(region="north")
    holidays = cal.holidays(2024)

    source = get_or_create_source(
        "workalendar", model="NL-north", source_type="CLI script"
    )

    annotations = []
    for date, name in holidays:
        start = pd.Timestamp(date).tz_localize("Europe/Amsterdam")
        end = start + pd.offsets.DateOffset(days=1)
        ann, _ = get_or_create_annotation(
            Annotation(
                content=name, start=start, end=end, source=source, type="holiday"
            )
        )
        annotations.append(ann)

    # Attach to account 1 (the first account created in fresh_db)
    account = db.session.get(Account, 1)
    account.annotations += annotations
    db.session.commit()

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
            DataSource.model == "NL-north",
        )
    )
    assert count == len(holidays)
    assert count > 50, f"Expected >50 NL north school holidays in 2024, got {count}"


def test_add_holidays_by_package_german_school(
    app, fresh_db, setup_roles_users_fresh_db
):
    """Test adding German school holidays (Bavaria) for 2024 via the holidays package."""
    from flexmeasures.cli.data_add import add_holidays_by_package

    db = fresh_db
    runner = app.test_cli_runner()
    result = runner.invoke(
        add_holidays_by_package,
        [
            "--year",
            "2024",
            "--country",
            "DE",
            "--subdiv",
            "BY",
            "--category",
            "school",
            "--account",
            "1",
            "--timezone",
            "Europe/Berlin",
        ],
    )
    check_command_ran_without_error(result)
    assert "Successfully added" in result.output

    # Bavaria has ~91 school holiday days in 2024
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
            DataSource.model == "DE/BY",
        )
    )
    assert count > 50, f"Expected >50 DE/BY school holiday days in 2024, got {count}"


def test_annotation_regressors_loaded_in_pipeline(
    app, fresh_db, setup_roles_users_fresh_db
):
    """Test that annotation regressors are loaded correctly by BasePipeline.

    This test simulates a factory logistics use case: custom operational schedule
    annotations (e.g. factory shutdown periods) stored as 'label' type annotations,
    and verifies that the pipeline correctly loads them as a binary 0/1 future covariate.
    """
    from datetime import timedelta

    import pandas as pd
    from flexmeasures.data.models.annotations import get_or_create_annotation
    from flexmeasures.data.services.data_sources import get_or_create_source
    from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
    from flexmeasures.data.models.time_series import Sensor
    from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline

    db = fresh_db

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

    # Create a logistics schedule: factory shutdown on Jan 15-17, 2024 (UTC)
    source = get_or_create_source("test", model="logistics", source_type="CLI script")
    shutdown = Annotation(
        content="Factory shutdown - annual maintenance",
        start=pd.Timestamp("2024-01-15T00:00:00Z"),
        end=pd.Timestamp("2024-01-17T00:00:00Z"),
        source=source,
        type="label",
    )
    ann, _ = get_or_create_annotation(shutdown)

    factory_asset.annotations += [ann]
    db.session.commit()

    annotation_spec = {
        "asset_id": factory_asset.id,
        "annotation_type": "label",
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

    # Jan 15-16 (UTC naive) should be 1.0; Jan 14 and post-Jan 17 should be 0.0
    shutdown_hours = ann_df[
        (ann_df["event_start"] >= pd.Timestamp("2024-01-15"))
        & (ann_df["event_start"] < pd.Timestamp("2024-01-17"))
    ]
    assert (
        shutdown_hours[col_name] == 1.0
    ).all(), "Shutdown period should be marked as 1.0"

    non_shutdown = ann_df[ann_df["event_start"] < pd.Timestamp("2024-01-15")]
    assert (
        non_shutdown[col_name] == 0.0
    ).all(), "Non-shutdown period should be marked as 0.0"
