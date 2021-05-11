from datetime import timedelta

import pytest
from flask import url_for
from iso8601 import parse_date
from numpy import repeat

from flexmeasures.api.common.utils.api_utils import message_replace_name_with_ea
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v1.tests.utils import (
    message_for_post_meter_data,
    message_for_get_meter_data,
    count_connections_in_post_message,
)
from flexmeasures.data.models.assets import Asset


@pytest.mark.parametrize(
    "post_message",
    [
        message_for_post_meter_data(),
        message_for_post_meter_data(single_connection=True),
        message_for_post_meter_data(single_connection_group=True),
    ],
)
@pytest.mark.parametrize(
    "get_message",
    [
        message_for_get_meter_data(),
        message_for_get_meter_data(single_connection=False),
        message_for_get_meter_data(resolution="PT30M"),
    ],
)
def test_post_and_get_meter_data(
    setup_fresh_api_test_data, app, clean_redis, client, post_message, get_message
):
    """
    Tries to post meter data as a logged-in test user with the MDC role, which should succeed.
    There should be some ForecastingJobs waiting now.
    Then tries to get meter data, which should succeed, and should return the same meter data as was posted,
    or a downsampled version, if that was requested.
    """

    # post meter data
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    post_meter_data_response = client.post(
        url_for("flexmeasures_api_v1.post_meter_data"),
        json=message_replace_name_with_ea(post_message),
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_meter_data_response.json)
    assert post_meter_data_response.status_code == 200
    assert post_meter_data_response.json["type"] == "PostMeterDataResponse"

    # look for Forecasting jobs
    expected_connections = count_connections_in_post_message(post_message)
    assert (
        len(app.queues["forecasting"]) == 4 * expected_connections
    )  # four horizons times the number of assets
    horizons = repeat(
        [
            timedelta(hours=1),
            timedelta(hours=6),
            timedelta(hours=24),
            timedelta(hours=48),
        ],
        expected_connections,
    )
    jobs = sorted(app.queues["forecasting"].jobs, key=lambda x: x.kwargs["horizon"])
    for job, horizon in zip(jobs, horizons):
        assert job.kwargs["horizon"] == horizon
        assert job.kwargs["start"] == parse_date(post_message["start"]) + horizon
    for asset_name in ("CS 1", "CS 2", "CS 3"):
        if asset_name in str(post_message):
            asset = Asset.query.filter_by(name=asset_name).one_or_none()
            assert asset.id in [job.kwargs["asset_id"] for job in jobs]

    # get meter data
    get_meter_data_response = client.get(
        url_for("flexmeasures_api_v1.get_meter_data"),
        query_string=message_replace_name_with_ea(get_message),
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_meter_data_response.json)
    assert get_meter_data_response.status_code == 200
    assert get_meter_data_response.json["type"] == "GetMeterDataResponse"
    if "groups" in post_message:
        posted_values = post_message["groups"][0]["values"]
    else:
        posted_values = post_message["values"]
    if "groups" in get_meter_data_response.json:
        gotten_values = get_meter_data_response.json["groups"][0]["values"]
    else:
        gotten_values = get_meter_data_response.json["values"]

    if "resolution" not in get_message or get_message["resolution"] == "":
        assert gotten_values == posted_values
    else:
        # We used a target resolution of 30 minutes, so double of 15 minutes.
        # Six values went in, three come out.
        if posted_values[1] > 0:  # see utils.py:message_for_post_meter_data
            assert gotten_values == [306.66, -0.0, 306.66]
        else:
            assert gotten_values == [153.33, 0, 306.66]
