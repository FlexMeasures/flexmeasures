from flask import url_for
import pytest

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token, UserContext


@pytest.mark.parametrize("use_auth", [False, True])
def test_get_users_bad_auth(client, use_auth):
    """
    Attempt to get users with insufficient or missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    query = {}
    if use_auth:
        # in this case, we successfully authenticate,
        # but fail authorization (non-admin accessing another account)
        headers["Authorization"] = get_auth_token(
            client, "test_prosumer_user_2@seita.nl", "testtest"
        )
        query = {"account_id": 2}

    get_users_response = client.get(
        url_for("flexmeasures_api_v2_0.get_users"), headers=headers, query_string=query
    )
    print("Server responded with:\n%s" % get_users_response.data)
    if use_auth:
        assert get_users_response.status_code == 403
    else:
        assert get_users_response.status_code == 401


@pytest.mark.parametrize("include_inactive", [False, True])
def test_get_users_inactive(client, setup_inactive_user, include_inactive):
    headers = {
        "content-type": "application/json",
        "Authorization": get_auth_token(
            client, "test_prosumer_user_2@seita.nl", "testtest"
        ),
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


@pytest.mark.parametrize(
    "requesting_user,status_code",
    [
        (None, 401),  # no auth is not allowed
        ("test_prosumer_user_2@seita.nl", 200),  # gets themselves
        ("test_prosumer_user@seita.nl", 200),  # gets from same account
        ("test_dummy_user_3@seita.nl", 403),  # gets from other account
        ("test_admin_user@seita.nl", 200),  # admin can do this from another account
    ],
)
def test_get_one_user(client, requesting_user, status_code):
    test_user2_id = find_user_by_email("test_prosumer_user_2@seita.nl").id
    headers = {"content-type": "application/json"}
    if requesting_user:
        headers["Authorization"] = get_auth_token(client, requesting_user, "testtest")

    get_user_response = client.get(
        url_for("flexmeasures_api_v2_0.get_user", id=test_user2_id),
        headers=headers,
    )
    print("Server responded with:\n%s" % get_user_response.data)
    assert get_user_response.status_code == status_code
    if status_code == 200:
        assert get_user_response.json["username"] == "Test Prosumer User 2"


def test_edit_user(client):
    with UserContext("test_prosumer_user_2@seita.nl") as user2:
        user2_auth_token = user2.get_auth_token()  # user2 is no admin
        user2_id = user2.id
    with UserContext("test_admin_user@seita.nl") as admin:
        admin_auth_token = admin.get_auth_token()
        admin_id = admin.id
    # without being the user themselves or an admin, the user cannot be edited
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=admin_id),
        headers={
            "content-type": "application/json",
            "Authorization": user2_auth_token,
        },
        json={},
    )
    assert user_edit_response.status_code == 403
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=user2_id),
        headers={"content-type": "application/json"},
        json={},
    )
    assert user_edit_response.status_code == 401
    # admin can deactivate user2, other changes will be ignored
    # (id is in the User schema of the API, but we ignore it)
    headers = {"content-type": "application/json", "Authorization": admin_auth_token}
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=user2_id),
        headers=headers,
        json={"active": False, "id": 888},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 200
    assert user_edit_response.json["active"] is False
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl")
    assert user2.active is False
    assert user2.id == user2_id
    # admin can edit themselves but not sensitive fields
    headers = {"content-type": "application/json", "Authorization": admin_auth_token}
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=admin_id),
        headers=headers,
        json={"active": False},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 403


def test_edit_user_with_unexpected_fields(client):
    """Sending unexpected fields (not in Schema) is an Unprocessable Entity error."""
    with UserContext("test_prosumer_user_2@seita.nl") as user2:
        user2_id = user2.id
    with UserContext("test_admin_user@seita.nl") as admin:
        admin_auth_token = admin.get_auth_token()
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=user2_id),
        headers={
            "content-type": "application/json",
            "Authorization": admin_auth_token,
        },
        json={"active": False, "password": "I-should-not-be-sending-this"},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 422
