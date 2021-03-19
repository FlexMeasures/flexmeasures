from flask import url_for
import pytest
from datetime import timedelta
from iso8601 import parse_date

from flexmeasures.api.common.utils.api_utils import get_generic_asset
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v2_0.tests.utils import (
    message_for_post_price_data,
    message_for_post_prognosis,
    verify_sensor_data_in_db,
)


@pytest.mark.parametrize(
    "post_message",
    [
        message_for_post_price_data(),
        message_for_post_price_data(prior_instead_of_horizon=True),
    ],
)
def test_post_price_data_2_0(db, app, post_message):
    """
    Try to post price data as a logged-in test user with the Supplier role, which should succeed.
    """
    # call with client whose context ends, so that we can test for,
    # after-effects in the database after teardown committed.
    with app.test_client() as client:
        # post price data
        auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
        post_price_data_response = client.post(
            url_for("flexmeasures_api_v2_0.post_price_data"),
            json=post_message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_price_data_response.json)
        assert post_price_data_response.status_code == 200
        assert post_price_data_response.json["type"] == "PostPriceDataResponse"

    verify_sensor_data_in_db(
        post_message, post_message["values"], db, entity_type="market"
    )

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
    "post_message",
    [
        message_for_post_prognosis(),
    ],
)
def test_post_prognosis(db, app, post_message):
    with app.test_client() as client:
        # post price data
        auth_token = get_auth_token(client, "test_supplier@seita.nl", "testtest")
        post_prognosis_response = client.post(
            url_for("flexmeasures_api_v2_0.post_prognosis"),
            json=post_message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_prognosis_response.json)
        assert post_prognosis_response.status_code == 200
        assert post_prognosis_response.json["type"] == "PostPrognosisResponse"

    verify_sensor_data_in_db(
        post_message,
        post_message["values"],
        db,
        entity_type="connection",
        swapped_sign=True,
    )
