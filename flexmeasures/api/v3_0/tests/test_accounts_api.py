from __future__ import annotations

from flask import url_for
import pytest

from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),
    ],
    indirect=["requesting_user"],
)
def test_get_accounts_missing_auth(client, requesting_user, status_code):
    """
    Attempt to get accounts with missing auth.
    """
    # the case without auth: authentication will fail
    get_accounts_response = client.get(url_for("AccountAPI:index"))
    print("Server responded with:\n%s" % get_accounts_response.data)
    assert get_accounts_response.status_code == status_code


@pytest.mark.parametrize(
    "requesting_user, num_accounts",
    [
        ("test_admin_user@seita.nl", 7),
        ("test_prosumer_user@seita.nl", 1),
        ("test_consultant@seita.nl", 2),
        ("test_consultancy_user_without_consultant_access@seita.nl", 1),
    ],
    indirect=["requesting_user"],
)
def test_get_accounts(client, setup_api_test_data, requesting_user, num_accounts):
    """
    Get accounts for:
    - A normal user.
    - An admin user.
    - A user with a consultant role, belonging to a consultancy account with a linked consultancy client account.
    - A user without a consultant role, belonging to a consultancy account with a linked consultancy client account.
    """
    get_accounts_response = client.get(
        url_for("AccountAPI:index"),
    )
    print("Server responded with:\n%s" % get_accounts_response.data)
    assert len(get_accounts_response.json) == num_accounts
    account_names = [a["name"] for a in get_accounts_response.json]
    assert requesting_user.account.name in account_names


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),  # no auth is not allowed
        ("test_prosumer_user_2@seita.nl", 200),  # gets their own account, okay
        ("test_dummy_user_3@seita.nl", 403),  # gets from other account
        ("test_admin_user@seita.nl", 200),  # admin can do this from another account
    ],
    indirect=["requesting_user"],
)
def test_get_one_account(client, setup_api_test_data, requesting_user, status_code):
    """Get one account"""
    test_user2_account_id = find_user_by_email(
        "test_prosumer_user_2@seita.nl"
    ).account.id
    get_account_response = client.get(
        url_for("AccountAPI:get", id=test_user2_account_id),
    )
    print("Server responded with:\n%s" % get_account_response.data)
    assert get_account_response.status_code == status_code
    if status_code == 200:
        assert get_account_response.json["name"] == "Test Prosumer Account"
        assert get_account_response.json["account_roles"] == [
            {"id": 1, "name": "Prosumer"}
        ]
