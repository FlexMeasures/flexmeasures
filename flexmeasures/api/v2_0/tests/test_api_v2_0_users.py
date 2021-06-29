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
def test_get_users_inactive(client, setup_inactive_user, include_inactive):
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


def test_edit_user(client):
    with UserContext("test_supplier@seita.nl") as supplier:
        supplier_auth_token = supplier.get_auth_token()  # supplier is no admin
        supplier_id = supplier.id
    with UserContext("test_prosumer@seita.nl") as prosumer:
        prosumer_auth_token = prosumer.get_auth_token()  # prosumer is an admin
        prosumer_id = prosumer.id
    # without being the user themselves or an admin, the user cannot be edited
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=prosumer_id),
        headers={
            "content-type": "application/json",
            "Authorization": supplier_auth_token,
        },
        json={},
    )
    assert user_edit_response.status_code == 403
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=supplier_id),
        headers={"content-type": "application/json"},
        json={},
    )
    assert user_edit_response.status_code == 401
    # admin can deactivate supplier, other changes will be ignored
    # (id is in the User schema of the API, but we ignore it)
    headers = {"content-type": "application/json", "Authorization": prosumer_auth_token}
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=supplier_id),
        headers=headers,
        json={"active": False, "id": 888},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 200
    assert user_edit_response.json["active"] is False
    supplier = find_user_by_email("test_supplier@seita.nl")
    assert supplier.active is False
    assert supplier.id == supplier_id
    # admin can edit themselves but not sensitive fields
    headers = {"content-type": "application/json", "Authorization": prosumer_auth_token}
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=prosumer_id),
        headers=headers,
        json={"active": False},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 403


def test_edit_user_with_unexpected_fields(client):
    """Sending unexpected fields (not in Schema) is an Unprocessable Entity error."""
    with UserContext("test_supplier@seita.nl") as supplier:
        supplier_id = supplier.id
    with UserContext("test_prosumer@seita.nl") as prosumer:
        prosumer_auth_token = prosumer.get_auth_token()  # prosumer is an admin
    user_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_user", id=supplier_id),
        headers={
            "content-type": "application/json",
            "Authorization": prosumer_auth_token,
        },
        json={"active": False, "password": "I-should-not-be-sending-this"},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 422
