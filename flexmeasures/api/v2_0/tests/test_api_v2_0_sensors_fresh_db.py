from datetime import timedelta

import pytest
from flask import url_for
from iso8601 import parse_date

from flexmeasures.api.common.schemas.sensors import SensorField
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v2_0.tests.utils import (
    message_for_post_price_data,
    verify_sensor_data_in_db,
)


@pytest.mark.parametrize(
    "post_message",
    [
        message_for_post_price_data(market_id=7),
        message_for_post_price_data(market_id=1, prior_instead_of_horizon=True),
    ],
)
def test_post_price_data_2_0(
    fresh_db,
    setup_roles_users_fresh_db,
    setup_markets_fresh_db,
    clean_redis,
    app,
    post_message,
):
    """
    Try to post price data as a logged-in test user with the Supplier role, which should succeed.
    """
    db = fresh_db
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
        post_message, post_message["values"], db, entity_type="market", fm_scheme="fm1"
    )

    # look for Forecasting jobs in queue
    assert (
        len(app.queues["forecasting"]) == 2
    )  # only one market is affected, but two horizons
    horizons = [timedelta(hours=24), timedelta(hours=48)]
    jobs = sorted(app.queues["forecasting"].jobs, key=lambda x: x.kwargs["horizon"])
    market = SensorField("market", fm_scheme="fm1").deserialize(post_message["market"])
    for job, horizon in zip(jobs, horizons):
        assert job.kwargs["horizon"] == horizon
        assert job.kwargs["start"] == parse_date(post_message["start"]) + horizon
        assert job.kwargs["timed_value_type"] == "Price"
        assert job.kwargs["asset_id"] == market.id
