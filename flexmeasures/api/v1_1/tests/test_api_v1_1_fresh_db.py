from datetime import timedelta
from iso8601 import parse_date

import pytest
from flask import url_for
from isodate import duration_isoformat

from flexmeasures.utils.time_utils import forecast_horizons_for
from flexmeasures.api.common.responses import unapplicable_resolution
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v1_1.tests.utils import (
    message_for_post_price_data,
    message_for_post_weather_data,
    verify_prices_in_db,
    get_forecasting_jobs,
)


@pytest.mark.parametrize(
    "post_message, status, msg",
    [
        (
            message_for_post_price_data(
                duration=duration_isoformat(timedelta(minutes=2))
            ),
            400,
            unapplicable_resolution()[0]["message"],
        ),
        (message_for_post_price_data(compress_n=4), 200, "Request has been processed."),
    ],
)
def test_post_price_data_unexpected_resolution(
    setup_fresh_api_v1_1_test_data, app, client, post_message, status, msg
):
    """
    Try to post price data with an unexpected resolution,
    which might be fixed with upsampling or otherwise fail.
    """
    db = setup_fresh_api_v1_1_test_data
    auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
    post_price_data_response = client.post(
        url_for("flexmeasures_api_v1_1.post_price_data"),
        json=post_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_price_data_response.json)
    assert post_price_data_response.json["type"] == "PostPriceDataResponse"
    assert post_price_data_response.status_code == status
    assert msg in post_price_data_response.json["message"]
    if "processed" in msg:
        verify_prices_in_db(
            post_message, [v for v in post_message["values"] for i in range(4)], db
        )


@pytest.mark.parametrize(
    "post_message",
    [message_for_post_weather_data(as_forecasts=False)],
)
def test_post_weather_data(
    setup_fresh_api_v1_1_test_data,
    add_weather_sensors_fresh_db,
    app,
    client,
    post_message,
):
    """
    Try to post wind speed data as a logged-in test user, which should lead to forecasting jobs.
    """
    auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
    post_weather_data_response = client.post(
        url_for("flexmeasures_api_v1_1.post_weather_data"),
        json=post_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_weather_data_response.json)
    assert post_weather_data_response.status_code == 200
    assert post_weather_data_response.json["type"] == "PostWeatherDataResponse"

    forecast_horizons = forecast_horizons_for(timedelta(minutes=5))
    jobs = get_forecasting_jobs("Weather")
    for job, horizon in zip(
        sorted(jobs, key=lambda x: x.kwargs["horizon"]), forecast_horizons
    ):
        # check if jobs have expected horizons
        assert job.kwargs["horizon"] == horizon
        # check if jobs' start time (the time to be forecasted)
        # is the weather observation plus the horizon
        assert job.kwargs["start"] == parse_date(post_message["start"]) + horizon
