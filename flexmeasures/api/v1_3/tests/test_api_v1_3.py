from flask import url_for
import pytest
from datetime import timedelta
from isodate import parse_datetime

import pandas as pd
from rq.job import Job

from flexmeasures.api.common.responses import unrecognized_event, unknown_schedule
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v1_3.tests.utils import (
    message_for_get_device_message,
    message_for_post_udi_event,
)
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.utils.calculations import integrate_time_series


@pytest.mark.parametrize("message", [message_for_get_device_message(wrong_id=True)])
def test_get_device_message_wrong_event_id(client, message):
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_3.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 400
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert (
        get_device_message_response.json["status"]
        == unrecognized_event(9999, "soc")[0]["status"]
    )


@pytest.mark.parametrize(
    "message, asset_name",
    [
        (message_for_post_udi_event(), "Test battery"),
        (message_for_post_udi_event(targets=True), "Test charging station"),
    ],
)
def test_post_udi_event_and_get_device_message(app, message, asset_name):
    auth_token = None
    with app.test_client() as client:
        asset = Asset.query.filter(Asset.name == asset_name).one_or_none()
        asset_id = asset.id
        asset_owner_id = asset.owner_id
        message["event"] = message["event"] % (asset.owner_id, asset.id)
        auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
        post_udi_event_response = client.post(
            url_for("flexmeasures_api_v1_3.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 200
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"

    # test asset state in database
    msg_dt = parse_datetime(message["datetime"])
    asset = Asset.query.filter(Asset.name == asset_name).one_or_none()
    assert asset.soc_datetime == msg_dt
    assert asset.soc_in_mwh == message["value"] / 1000
    assert asset.soc_udi_event_id == 204

    # look for scheduling jobs in queue
    assert (
        len(app.queues["scheduling"]) == 1
    )  # only 1 schedule should be made for 1 asset
    job = app.queues["scheduling"].jobs[0]
    assert job.kwargs["asset_id"] == asset_id
    assert job.kwargs["start"] == parse_datetime(message["datetime"])
    assert job.id == message["event"]

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(
            message["event"], connection=app.queues["scheduling"].connection
        ).is_finished
        is True
    )

    # check results are in the database
    resolution = timedelta(minutes=15)
    scheduler_source = DataSource.query.filter_by(
        name="Seita", type="scheduling script"
    ).one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there
    power_values = (
        Power.query.filter(Power.asset_id == asset_id)
        .filter(Power.data_source_id == scheduler_source.id)
        .all()
    )
    consumption_schedule = pd.Series(
        [-v.value for v in power_values],
        index=pd.DatetimeIndex([v.datetime for v in power_values], freq=resolution),
    )  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
    assert (
        len(consumption_schedule)
        == app.config.get("FLEXMEASURES_PLANNING_HORIZON") / resolution
    )

    # check targets, if applicable
    if "targets" in message:
        start_soc = message["value"] / 1000  # in MWh
        soc_schedule = integrate_time_series(consumption_schedule, start_soc, 6)
        print(consumption_schedule)
        print(soc_schedule)
        for target in message["targets"]:
            assert soc_schedule[target["datetime"]] == target["value"] / 1000

    # try to retrieve the schedule through the getDeviceMessage api endpoint
    get_device_message = message_for_get_device_message()
    get_device_message["event"] = get_device_message["event"] % (
        asset_owner_id,
        asset_id,
    )
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_3.get_device_message"),
        query_string=get_device_message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 200
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert len(get_device_message_response.json["values"]) == 192

    # Test that a shorter planning horizon yields the same result for the shorter planning horizon
    get_device_message["duration"] = "PT6H"
    get_device_message_response_short = client.get(
        url_for("flexmeasures_api_v1_3.get_device_message"),
        query_string=get_device_message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert (
        get_device_message_response_short.json["values"]
        == get_device_message_response.json["values"][0:24]
    )

    # Test that a much longer planning horizon yields the same result (when there are only 2 days of prices)
    get_device_message["duration"] = "PT1000H"
    get_device_message_response_long = client.get(
        url_for("flexmeasures_api_v1_3.get_device_message"),
        query_string=get_device_message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert (
        get_device_message_response_long.json["values"][0:192]
        == get_device_message_response.json["values"]
    )

    # sending again results in an error, unless we increase the event ID
    with app.test_client() as client:
        next_msg_dt = msg_dt + timedelta(minutes=5)
        message["datetime"] = next_msg_dt.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        post_udi_event_response = client.post(
            url_for("flexmeasures_api_v1_3.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 400
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"
        assert post_udi_event_response.json["status"] == "OUTDATED_UDI_EVENT"

        message["event"] = message["event"].replace("204", "205")
        post_udi_event_response = client.post(
            url_for("flexmeasures_api_v1_3.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 200
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"

    # test database state
    asset = Asset.query.filter(Asset.name == asset_name).one_or_none()
    assert asset.soc_datetime == next_msg_dt
    assert asset.soc_in_mwh == message["value"] / 1000
    assert asset.soc_udi_event_id == 205

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    # the job still fails due to missing prices for the last time slot, but we did test that the api and worker now processed the UDI event and attempted to create a schedule
    assert (
        Job.fetch(
            message["event"], connection=app.queues["scheduling"].connection
        ).is_failed
        is True
    )


@pytest.mark.parametrize("message", [message_for_post_udi_event(unknown_prices=True)])
def test_post_udi_event_and_get_device_message_with_unknown_prices(app, message):
    auth_token = None
    with app.test_client() as client:
        asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
        asset_id = asset.id
        asset_owner_id = asset.owner_id
        message["event"] = message["event"] % (asset.owner_id, asset.id)
        auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
        post_udi_event_response = client.post(
            url_for("flexmeasures_api_v1_3.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 200
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"

        # look for scheduling jobs in queue
        assert (
            len(app.queues["scheduling"]) == 1
        )  # only 1 schedule should be made for 1 asset
        job = app.queues["scheduling"].jobs[0]
        assert job.kwargs["asset_id"] == asset_id
        assert job.kwargs["start"] == parse_datetime(message["datetime"])
        assert job.id == message["event"]
        assert (
            Job.fetch(message["event"], connection=app.queues["scheduling"].connection)
            == job
        )

        # process the scheduling queue
        work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
        processed_job = Job.fetch(
            message["event"], connection=app.queues["scheduling"].connection
        )
        assert processed_job.is_failed is True

        # check results are not in the database
        scheduler_source = DataSource.query.filter_by(
            name="Seita", type="scheduling script"
        ).one_or_none()
        assert (
            scheduler_source is None
        )  # Make sure the scheduler data source is still not there

        # try to retrieve the schedule through the getDeviceMessage api endpoint
        message = message_for_get_device_message()
        message["event"] = message["event"] % (asset_owner_id, asset_id)
        auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
        get_device_message_response = client.get(
            url_for("flexmeasures_api_v1_3.get_device_message"),
            query_string=message,
            headers={"content-type": "application/json", "Authorization": auth_token},
        )
        print("Server responded with:\n%s" % get_device_message_response.json)
        assert get_device_message_response.status_code == 400
        assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
        assert (
            get_device_message_response.json["status"]
            == unknown_schedule()[0]["status"]
        )
        assert "prices unknown" in get_device_message_response.json["message"].lower()
