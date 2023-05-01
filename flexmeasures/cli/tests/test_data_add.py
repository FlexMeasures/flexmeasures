import pytest

# import json
# from datetime import datetime, timedelta
# from pytz import utc
# import os


from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource

# from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
# from flexmeasures.data.models.time_series import Sensor, TimedBelief

from flexmeasures.cli.tests.utils import get_click_commands


@pytest.mark.skip_github
def test_add_annotation(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_annotation

    cli_input = {
        "content": "Company founding day",
        "at": "2016-05-11T00:00+02:00",
        "account-id": 1,
        "user-id": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_annotation, to_flags(cli_input))

    # Check result for success
    assert "Successfully added annotation" in result.output

    # Check database for annotation entry
    assert (
        Annotation.query.filter(
            Annotation.content == cli_input["content"],
            Annotation.start == cli_input["at"],
        )
        .join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == cli_input["account-id"],
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.user_id == cli_input["user-id"],
        )
        .one_or_none()
    )


@pytest.mark.skip_github
def test_add_holidays(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_holidays

    cli_input = {
        "year": 2020,
        "country": "NL",
        "account-id": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_holidays, to_flags(cli_input))

    # Check result for 11 public holidays
    assert "'NL': 11" in result.output

    # Check database for 11 annotation entries
    assert (
        Annotation.query.join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == cli_input["account-id"],
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.name == "workalendar",
            DataSource.model == cli_input["country"],
        )
        .count()
        == 11
    )


@pytest.mark.skip_github
def test_cli_help(app):
    """Test that showing help does not throw an error."""
    from flexmeasures.cli import data_add

    runner = app.test_cli_runner()
    for cmd in get_click_commands(data_add):
        result = runner.invoke(cmd, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


# @pytest.fixture
# def setup_dummy_data_2(db, app):

#     """
#     Create Sensors 2, 1 Asset and 1 AssetType
#     """
#     dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")
#     report_asset_type = GenericAssetType(name="ReportAssetType")

#     db.session.add_all([dummy_asset_type, report_asset_type])

#     dummy_asset = GenericAsset(
#         name="DummyGenericAsset", generic_asset_type=dummy_asset_type
#     )

#     pandas_report = GenericAsset(
#         name="PandasReport", generic_asset_type=report_asset_type
#     )

#     db.session.add_all([dummy_asset, pandas_report])

#     sensor1 = Sensor(
#         "sensor 1", generic_asset=dummy_asset, event_resolution=timedelta(hours=1)
#     )

#     db.session.add(sensor1)
#     sensor2 = Sensor(
#         "sensor 2", generic_asset=dummy_asset, event_resolution=timedelta(hours=1)
#     )
#     db.session.add(sensor2)
#     report_sensor = Sensor(
#         "report sensor",
#         generic_asset=pandas_report,
#         event_resolution=timedelta(hours=2),
#     )
#     db.session.add(report_sensor)

#     """
#         Create 1 DataSources
#     """
#     source = DataSource("source1")

#     """
#         Create TimedBeliefs
#     """
#     beliefs = []
#     for sensor in [sensor1, sensor2]:
#         for t in range(20):
#             beliefs.append(
#                 TimedBelief(
#                     event_start=datetime(2023, 4, 10, tzinfo=utc) + timedelta(hours=t),
#                     belief_time=datetime(2023, 4, 9, tzinfo=utc),
#                     event_value=t,
#                     sensor=sensor,
#                     source=source,
#                 )
#             )

#     db.session.add_all(beliefs)
#     db.session.commit()

#     yield sensor1, sensor2, report_sensor

#     db.session.delete(sensor1)
#     db.session.delete(sensor2)

#     for b in beliefs:
#         db.session.delete(b)

#     db.session.delete(dummy_asset)
#     db.session.delete(dummy_asset_type)

#     db.session.commit()


# @pytest.fixture
# def reporter_config_raw(app, db, setup_dummy_data_2):
#     sensor1, sensor2, report_sensor = setup_dummy_data_2

#     reporter_config_raw = dict(
#         start="2023-04-10T00:00:00 00:00",
#         end="2023-04-10T10:00:00 00:00",
#         tb_query_config=[dict(sensor=sensor1.id), dict(sensor=sensor2.id)],
#         transformations=[
#             dict(
#                 df_input="sensor_1",
#                 df_output="df_agg",
#                 method="add",
#                 args=["@sensor_2"],
#             ),
#             dict(method="resample_events", args=["2h"]),
#         ],
#         final_df_output="df_agg",
#     )

#     return reporter_config_raw


# def test_add_reporter(app, db, setup_dummy_data_2, reporter_config_raw):
#     from flexmeasures.cli.data_add import add_report

#     sensor1, sensor2, report_sensor = setup_dummy_data_2
#     report_sensor_id = report_sensor.id

#     runner = app.test_cli_runner()

#     cli_input_params = {
#         "sensor-id": report_sensor_id,
#         "reporter-config-file": "reporter_config.json",
#         "reporter": "PandasReporter",
#         "start": "2023-04-10T00:00:00 00:00",
#         "end": "2023-04-10T10:00:00 00:00",
#         "timezone": "UTC",
#         "output_file": "test.csv",
#     }

#     cli_input = to_flags(cli_input_params)

#     flags = ["--save-to-database"]
#     cli_input.extend(flags)

#     with runner.isolated_filesystem():

#         # save reporter_config to a json file
#         with open("reporter_config.json", "w") as f:
#             json.dump(reporter_config_raw, f)

#         # call command
#         result = runner.invoke(add_report, cli_input)

#         print(result)

#         assert result.exit_code == 0  # run command without errors

#         assert "Reporter PandasReporter found" in result.output
#         assert "Report computation done." in result.output

#         # Check report is save to the database
#         report_sensor = (
#             db.session.query(Sensor).filter(Sensor.id == report_sensor_id).one_or_none()
#         )  # get fresh report sensor instance
#         stored_report = report_sensor.search_beliefs(
#             event_starts_after=cli_input_params.get("start").replace(" ", "+"),
#             event_ends_before=cli_input_params.get("end").replace(" ", "+"),
#         )
#         assert len(stored_report) == 5

#         assert os.path.exists("test.csv")  # check that the file has been created
#         assert (
#             os.path.getsize("test.csv") > 100
#         )  # bytes. Check that the file is not empty
