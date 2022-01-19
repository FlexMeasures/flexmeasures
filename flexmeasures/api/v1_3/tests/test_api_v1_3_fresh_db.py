import pytest
from flask import url_for
from isodate import parse_datetime
from rq.job import Job

from flexmeasures.api.common.responses import unknown_schedule
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v1_3.tests.utils import (
    message_for_post_udi_event,
    message_for_get_device_message,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.data.tests.utils import work_on_rq


@pytest.mark.parametrize("message", [message_for_post_udi_event(unknown_prices=True)])
def test_post_udi_event_and_get_device_message_with_unknown_prices(
    setup_fresh_api_test_data, clean_redis, app, message
):
    auth_token = None
    with app.test_client() as client:
        sensor = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
        message["event"] = message["event"] % sensor.id
        auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
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
        assert job.kwargs["asset_id"] == sensor.id
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
        message["event"] = message["event"] % sensor.id
        auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
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
