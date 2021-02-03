from flask import url_for
import pytest

from flexmeasures.data.models.user import User
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token, UserContext


@pytest.mark.parametrize("use_auth", [False, True])
def test_get_users_bad_auth(client, use_auth):
    """
    Attempt to get users with insufficient or missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    if use_auth:
        # in this case, we successfully authenticate, 
        # but fail authorization (no admin)
        headers["Authorization"] = get_auth_token(
            client, "test_supplier@seita.nl", "testtest"
        )

    get_users_response = client.get(
        url_for("flexmeasures_api_v2_1.Users"), headers=headers
    )
    print("Server responded with:\n%s" % get_users_response.data)
    if use_auth:
        assert get_users_response.status_code == 403
    else:
        assert get_users_response.status_code == 401


# TODO: test with and without inactive toggle
def test_get_users(client):
    headers = {"content-type": "application/json",
               "Authorization": get_auth_token(
                    client, "test_prosumer@seita.nl", "testtest"
                )
              }
    get_users_response = client.get(
        url_for("flexmeasures_api_v2_1.Users"), headers=headers
    )
    print("Server responded with:\n%s" % get_users_response.json)
