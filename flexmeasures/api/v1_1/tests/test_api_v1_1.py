from flask import url_for
import pytest
from datetime import timedelta
from isodate import duration_isoformat
from iso8601 import parse_date

from flexmeasures.utils.entity_address_utils import parse_entity_address
from flexmeasures.api.common.responses import (
    request_processed,
    invalid_horizon,
    unapplicable_resolution,
    invalid_unit,
)
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.common.utils.api_utils import (
    get_generic_asset,
    message_replace_name_with_ea,
)
from flexmeasures.api.v1_1.tests.utils import (
    message_for_get_prognosis,
    message_for_post_price_data,
    message_for_post_weather_data,
    verify_prices_in_db,
)
from flexmeasures.data.auth_setup import UNAUTH_ERROR_STATUS

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import User
from flexmeasures.data.models.markets import Market


@pytest.mark.parametrize("query", [{}, {"access": "Prosumer"}])
def test_get_service(client, query):
    get_service_response = client.get(
        url_for("flexmeasures_api_v1_1.get_service"),
        query_string=query,
        headers={"content-type": "application/json"},
    )
    print("Server responded with:\n%s" % get_service_response.json)
    assert get_service_response.status_code == 200
    assert get_service_response.json["type"] == "GetServiceResponse"
    assert get_service_response.json["status"] == request_processed()[0]["status"]
    if "access" in query:
        for service in get_service_response.json["services"]:
            assert "Prosumer" in service["access"]


def test_unauthorized_prognosis_request(client):
    get_prognosis_response = client.get(
        url_for("flexmeasures_api_v1_1.get_prognosis"),
        query_string=message_for_get_prognosis(),
        headers={"content-type": "application/json"},
    )
    print("Server responded with:\n%s" % get_prognosis_response.json)
    assert get_prognosis_response.status_code == 401
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    assert get_prognosis_response.json["status"] == UNAUTH_ERROR_STATUS


@pytest.mark.parametrize(
    "message",
    [
        message_for_get_prognosis(invalid_horizon=True),
    ],
)
def test_invalid_horizon(client, message):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_prognosis_response = client.get(
        url_for("flexmeasures_api_v1_1.get_prognosis"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_prognosis_response.json)
    assert get_prognosis_response.status_code == 400
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    assert get_prognosis_response.json["status"] == invalid_horizon()[0]["status"]


def test_no_data(client):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_prognosis_response = client.get(
        url_for("flexmeasures_api_v1_1.get_prognosis"),
        query_string=message_replace_name_with_ea(
            message_for_get_prognosis(no_data=True)
        ),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_prognosis_response.json)
    assert get_prognosis_response.status_code == 200
    assert get_prognosis_response.json["type"] == "GetPrognosisResponse"
    assert get_prognosis_response.json["values"] == []


@pytest.mark.parametrize(
    "message",
    [
        message_for_get_prognosis(),
        message_for_get_prognosis(single_connection=False),
        message_for_get_prognosis(single_connection=True),
        message_for_get_prognosis(no_resolution=True),
        message_for_get_prognosis(rolling_horizon=True),
        message_for_get_prognosis(with_prior=True),
        message_for_get_prognosis(rolling_horizon=True, timezone_alternative=True),
    ],
)
def test_get_prognosis(client, message):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_prognosis_response = client.get(
        url_for("flexmeasures_api_v1_1.get_prognosis"),
        query_string=message_replace_name_with_ea(message),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_prognosis_response.json)
    assert get_prognosis_response.status_code == 200
    if "groups" in get_prognosis_response.json:
        assert get_prognosis_response.json["groups"][0]["values"] == [
            300,
            301,
            302,
            303,
            304,
            305,
        ]
    else:
        assert get_prognosis_response.json["values"] == [300, 301, 302, 303, 304, 305]


@pytest.mark.parametrize("post_message", [message_for_post_price_data()])
def test_post_price_data(db, app, post_message):
    """
    Try to post price data as a logged-in test user with the Supplier role, which should succeed.
    """
    # call with client whose context ends, so that we can test for,
    # after-effects in the database after teardown committed.
    with app.test_client() as client:
        # post price data
        auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
        post_price_data_response = client.post(
            url_for("flexmeasures_api_v1_1.post_price_data"),
            json=post_message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_price_data_response.json)
        assert post_price_data_response.status_code == 200
        assert post_price_data_response.json["type"] == "PostPriceDataResponse"

    verify_prices_in_db(post_message, post_message["values"], db)

    # look for Forecasting jobs in queue
    assert (
        len(app.queues["forecasting"]) == 2
    )  # only one market is affected, but two horizons
    horizons = [timedelta(hours=24), timedelta(hours=48)]
    jobs = sorted(app.queues["forecasting"].jobs, key=lambda x: x.kwargs["horizon"])
    market = get_generic_asset(post_message["market"], "market")
    for job, horizon in zip(jobs, horizons):
        assert job.kwargs["horizon"] == horizon
        assert job.kwargs["start"] == parse_date(post_message["start"]) + horizon
        assert job.kwargs["timed_value_type"] == "Price"
        assert job.kwargs["asset_id"] == market.id


@pytest.mark.parametrize(
    "post_message", [message_for_post_price_data(invalid_unit=True)]
)
def test_post_price_data_invalid_unit(client, post_message):
    """
    Try to post price data with the wrong unit, which should fail.
    """

    # post price data
    auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
    post_price_data_response = client.post(
        url_for("flexmeasures_api_v1_1.post_price_data"),
        json=post_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_price_data_response.json)
    assert post_price_data_response.status_code == 400
    assert post_price_data_response.json["type"] == "PostPriceDataResponse"
    market = parse_entity_address(post_message["market"], "market")
    market_name = market["market_name"]
    market = Market.query.filter_by(name=market_name).one_or_none()
    assert (
        post_price_data_response.json["message"]
        == invalid_unit("%s prices" % market.display_name, ["EUR/MWh"])[0]["message"]
    )


@pytest.mark.parametrize(
    "post_message,status,msg",
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
def test_post_price_data_unexpected_resolution(db, app, post_message, status, msg):
    """
    Try to post price data with an unexpected resolution,
    which might be fixed with upsampling or otherwise fail.
    """
    with app.test_client() as client:
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
    [message_for_post_weather_data(), message_for_post_weather_data(temperature=True)],
)
def test_post_weather_data(client, post_message):
    """
    Try to post wind speed data as a logged-in test user with the Supplier role, which should succeed.
    """

    # post weather data
    auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
    post_weather_data_response = client.post(
        url_for("flexmeasures_api_v1_1.post_weather_data"),
        json=post_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_weather_data_response.json)
    assert post_weather_data_response.status_code == 200
    assert post_weather_data_response.json["type"] == "PostWeatherDataResponse"


@pytest.mark.parametrize(
    "post_message", [message_for_post_weather_data(invalid_unit=True)]
)
def test_post_weather_data_invalid_unit(client, post_message):
    """
    Try to post wind speed data as a logged-in test user with the Supplier role, but with a wrong unit for wind speed,
    which should fail.
    """

    # post weather data
    auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
    post_weather_data_response = client.post(
        url_for("flexmeasures_api_v1_1.post_weather_data"),
        json=post_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_weather_data_response.json)
    assert post_weather_data_response.status_code == 400
    assert post_weather_data_response.json["type"] == "PostWeatherDataResponse"
    assert (
        post_weather_data_response.json["message"]
        == invalid_unit("wind speed", ["m/s"])[0]["message"]
    )  # also checks that any underscore in the physical or economic quantity should be replaced with a space


@pytest.mark.parametrize("post_message", [message_for_post_price_data()])
def test_auto_fix_missing_registration_of_user_as_data_source(client, post_message):
    """Try to post price data as a user that has not been properly registered as a data source.
    The API call should succeed and the user should be automatically registered as a data source.
    """

    # post price data
    auth_token = get_auth_token(client, "test_improper_user@seita.nl", "testtest")
    post_price_data_response = client.post(
        url_for("flexmeasures_api_v1_1.post_price_data"),
        json=post_message,
        headers={"Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_price_data_response.json)
    assert post_price_data_response.status_code == 200

    formerly_improper_user = User.query.filter(
        User.email == "test_improper_user@seita.nl"
    ).one_or_none()
    data_source = DataSource.query.filter(
        DataSource.user == formerly_improper_user
    ).one_or_none()
    assert data_source is not None
