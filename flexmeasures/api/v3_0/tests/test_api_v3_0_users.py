from flask import url_for
from flask_login import current_user, logout_user
import pytest

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import UserContext


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl", None], indirect=True
)
def test_get_users_bad_auth(requesting_user, client, setup_api_test_data):
    """
    Attempt to get users with insufficient or missing auth.
    """
    # the case without auth: authentication will fail
    query = {}
    if requesting_user:
        # in this case, we successfully authenticate,
        # but fail authorization (non-admin accessing another account)
        query = {"account_id": 2}

    get_users_response = client.get(url_for("UserAPI:index"), query_string=query)
    print("Server responded with:\n%s" % get_users_response.data)
    if requesting_user:
        assert get_users_response.status_code == 403
    else:
        assert get_users_response.status_code == 401


@pytest.mark.parametrize("include_inactive", [False, True])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_get_users_inactive(
    requesting_user, client, setup_api_test_data, setup_inactive_user, include_inactive
):
    query = {}
    if include_inactive in (True, False):
        query["include_inactive"] = include_inactive
    get_users_response = client.get(
        url_for("UserAPI:index"),
        query_string=query,
    )
    print("Server responded with:\n%s" % get_users_response.json)
    assert get_users_response.status_code == 200
    assert isinstance(get_users_response.json, list)
    if include_inactive is False:
        assert len(get_users_response.json) == 2
    else:
        assert len(get_users_response.json) == 4


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),  # no auth is not allowed
        ("test_prosumer_user_2@seita.nl", 200),  # gets themselves
        ("test_prosumer_user@seita.nl", 200),  # gets from same account
        ("test_dummy_user_3@seita.nl", 403),  # gets from other account
        ("test_admin_user@seita.nl", 200),  # admin can do this from another account
    ],
    indirect=["requesting_user"],
)
def test_get_one_user(client, setup_api_test_data, requesting_user, status_code):
    test_user2_id = find_user_by_email("test_prosumer_user_2@seita.nl").id

    get_user_response = client.get(url_for("UserAPI:get", id=test_user2_id))
    print("Server responded with:\n%s" % get_user_response.data)
    assert get_user_response.status_code == status_code
    if status_code == 200:
        assert get_user_response.json["username"] == "Test Prosumer User 2"


@pytest.mark.parametrize(
    "requesting_user, requested_user, status_code",
    [
        (
            "test_prosumer_user_2@seita.nl",
            "test_admin_user@seita.nl",
            403,
        ),  # without being the user themselves or an admin, the user cannot be edited
        (None, "test_prosumer_user_2@seita.nl", 401),  # anonymous user cannot edit
        (
            "test_admin_user@seita.nl",
            "test_prosumer_user_2@seita.nl",
            200,
        ),  # admin can deactivate user2
        (
            "test_admin_user@seita.nl",
            "test_admin_user@seita.nl",
            403,
        ),  # admin can edit themselves but not sensitive fields
    ],
    indirect=["requesting_user"],
)
def test_edit_user(
    requesting_user, requested_user, status_code, client, setup_api_test_data
):
    with UserContext(requested_user) as u:
        requested_user_id = u.id

    user_edit_response = client.patch(
        url_for("UserAPI:patch", id=requested_user_id),
        json={"active": False},
    )
    assert user_edit_response.status_code == status_code
    if status_code == 200:
        assert user_edit_response.json["active"] is False
        user = find_user_by_email(requested_user)
        assert user.active is False
        assert user.id == requested_user_id


@pytest.mark.parametrize(
    "unexpected_fields",
    [
        dict(password="I-should-not-be-sending-this"),  # not part of the schema
        dict(id=10),  # id is a dump_only field
        dict(account_id=10),  # account_id is a dump_only field
    ],
)
@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_edit_user_with_unexpected_fields(
    requesting_user, client, setup_api_test_data, unexpected_fields: dict
):
    """Sending unexpected fields (not in Schema) is an Unprocessable Entity error."""
    with UserContext("test_prosumer_user_2@seita.nl") as user2:
        user2_id = user2.id
    user_edit_response = client.patch(
        url_for("UserAPI:patch", id=user2_id),
        json={**{"active": False}, **unexpected_fields},
    )
    print("Server responded with:\n%s" % user_edit_response.json)
    assert user_edit_response.status_code == 422


@pytest.mark.parametrize(
    "email, status_code",
    [
        ("test_admin_user@seita.nl", 200),
        ("inactive_admin@seita.nl", 400),
    ],
)
def test_login(client, setup_api_test_data, email, status_code):
    """Tries to log in."""

    assert current_user.is_anonymous

    # log in
    login_response = client.post(
        url_for("security.login"),
        json={
            "email": email,
            "password": "testtest",
        },
    )
    print(login_response.json)

    assert login_response.status_code == status_code

    if status_code == 200:
        assert not current_user.is_anonymous
        logout_user()


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_logout(client, setup_api_test_data, requesting_user):
    """Tries to log out, which should succeed as a url direction."""

    assert not current_user.is_anonymous

    # log out
    logout_response = client.get(url_for("security.logout"))
    assert logout_response.status_code == 302

    assert current_user.is_anonymous
