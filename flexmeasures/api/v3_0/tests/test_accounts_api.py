from flask import url_for
import pytest

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token


def test_get_accounts_missing_auth(client):
    """
    Attempt to get accounts with missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    get_accounts_response = client.get(url_for("AccountAPI:index"), headers=headers)
    print("Server responded with:\n%s" % get_accounts_response.data)
    assert get_accounts_response.status_code == 401


@pytest.mark.parametrize("as_admin", [True, False])
def test_get_accounts(client, setup_api_test_data, as_admin):
    """
    Get accounts
    """
    headers = {"content-type": "application/json"}
    if as_admin:
        user_email = "test_admin_user@seita.nl"
    else:
        user_email = "test_prosumer_user@seita.nl"
    headers["Authorization"] = get_auth_token(client, user_email, "testtest")
    get_accounts_response = client.get(
        url_for("AccountAPI:index"),
        headers=headers,
    )
    print("Server responded with:\n%s" % get_accounts_response.data)
    if as_admin:
        assert len(get_accounts_response.json) == 3
    else:
        assert len(get_accounts_response.json) == 1
        get_accounts_response.json[0]["name"] == "Test Prosumer Account"


@pytest.mark.parametrize(
    "requesting_user,status_code",
    [
        (None, 401),  # no auth is not allowed
        ("test_prosumer_user_2@seita.nl", 200),  # gets their won account, ok
        ("test_dummy_user_3@seita.nl", 403),  # gets from other account
        ("test_admin_user@seita.nl", 200),  # admin can do this from another account
    ],
)
def test_get_one_account(client, setup_api_test_data, requesting_user, status_code):
    """Get one account"""
    test_user2_account_id = find_user_by_email(
        "test_prosumer_user_2@seita.nl"
    ).account.id
    headers = {"content-type": "application/json"}
    if requesting_user:
        headers["Authorization"] = get_auth_token(client, requesting_user, "testtest")

    get_account_response = client.get(
        url_for("AccountAPI:get", id=test_user2_account_id),
        headers=headers,
    )
    print("Server responded with:\n%s" % get_account_response.data)
    assert get_account_response.status_code == status_code
    if status_code == 200:
        assert get_account_response.json["name"] == "Test Prosumer Account"
        assert get_account_response.json["account_roles"] == [1]
