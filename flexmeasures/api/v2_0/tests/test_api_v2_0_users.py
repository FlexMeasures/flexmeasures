from flask import url_for
import pytest

# from flexmeasures.data.models.user import User
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token  # , UserContext


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
        url_for("flexmeasures_api_v2_0.get_users"),
        headers=headers,
    )
    print("Server responded with:\n%s" % get_users_response.data)
    if use_auth:
        assert get_users_response.status_code == 403
    else:
        assert get_users_response.status_code == 401


@pytest.mark.parametrize("include_inactive", [False, True])
def test_get_users_inactive(client, include_inactive):
    headers = {
        "content-type": "application/json",
        "Authorization": get_auth_token(client, "test_prosumer@seita.nl", "testtest"),
    }
    query = {}
    if include_inactive in (True, False):
        query["include_inactive"] = include_inactive
    get_users_response = client.get(
        url_for("flexmeasures_api_v2_0.get_users"), query_string=query, headers=headers
    )
    print("Server responded with:\n%s" % get_users_response.json)
    assert get_users_response.status_code == 200
    assert isinstance(get_users_response.json, list)
    if include_inactive is False:
        assert len(get_users_response.json) == 2
    else:
        assert len(get_users_response.json) == 3


def test_get_one_user(client):
    test_supplier_id = find_user_by_email("test_supplier@seita.nl").id
    headers = {
        "content-type": "application/json",
        "Authorization": get_auth_token(client, "test_prosumer@seita.nl", "testtest"),
    }

    get_user_response = client.get(
        url_for("flexmeasures_api_v2_0.get_user", id=test_supplier_id),
        headers=headers,
    )
    print("Server responded with:\n%s" % get_user_response.data)
    assert get_user_response.status_code == 200
    assert get_user_response.json["username"] == "Test Supplier"
