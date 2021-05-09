from flask import url_for
import pytest

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v2_0.tests.utils import (
    message_for_post_prognosis,
    verify_sensor_data_in_db,
)


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
