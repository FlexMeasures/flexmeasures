from __future__ import annotations

import json

from flask import url_for
import pytest
from sqlalchemy import select

from flexmeasures.data.models.user import Account, AccountRole
from flexmeasures.auth.policy import CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE
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
    "requesting_user, num_accounts, sort_by, sort_dir, expected_name_of_first_account",
    [
        ("test_admin_user@seita.nl", 7, None, None, None),
        ("test_prosumer_user@seita.nl", 1, None, None, None),
        ("test_consultant@seita.nl", 2, None, None, None),
        (
            "test_consultancy_user_without_consultant_access@seita.nl",
            1,
            None,
            None,
            None,
        ),
        ("test_admin_user@seita.nl", 7, "name", "asc", "Multi Role Account"),
        ("test_admin_user@seita.nl", 7, "name", "desc", "Test Supplier Account"),
    ],
    indirect=["requesting_user"],
)
def test_get_accounts(
    client,
    setup_api_test_data,
    requesting_user,
    num_accounts,
    sort_by,
    sort_dir,
    expected_name_of_first_account,
):
    """
    Get accounts for:
    - A normal user.
    - An admin user.
    - A user with a consultant role, belonging to a consultancy account with a linked consultancy client account.
    - A user without a consultant role, belonging to a consultancy account with a linked consultancy client account.
    """
    query = {}

    if sort_by:
        query["sort_by"] = sort_by

    if sort_dir:
        query["sort_dir"] = sort_dir

    get_accounts_response = client.get(
        url_for("AccountAPI:index"),
        query_string=query,
    )

    print("Server responded with:\n%s" % get_accounts_response.json)

    accounts = get_accounts_response.json
    assert len(accounts) == num_accounts
    account_names = [a["name"] for a in accounts]
    assert requesting_user.account.name in account_names

    if sort_by:
        assert accounts[0]["name"] == expected_name_of_first_account


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


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),  # no auth is not allowed
        (
            "test_prosumer_user@seita.nl",
            403,
        ),  # non account admin cant view account audit log
        (
            "test_prosumer_user_2@seita.nl",
            200,
        ),  # account-admin can view his account audit log
        (
            "test_dummy_account_admin@seita.nl",
            403,
        ),  # account-admin cannot view other account audit logs
        ("test_admin_user@seita.nl", 200),  # admin can view another account audit log
        (
            "test_admin_reader_user@seita.nl",
            200,
        ),  # admin reader can view another account audit log
    ],
    indirect=["requesting_user"],
)
def test_get_one_account_audit_log(
    client, setup_api_test_data, requesting_user, status_code
):
    """Get one account"""
    test_user_account_id = find_user_by_email("test_prosumer_user@seita.nl").account.id
    get_account_response = client.get(
        url_for("AccountAPI:auditlog", id=test_user_account_id),
    )
    print("Server responded with:\n%s" % get_account_response.data)
    assert get_account_response.status_code == status_code
    if status_code == 200:
        assert get_account_response.json[0] is not None


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        # Consultant users can see the audit log of all users in the client accounts.
        ("test_consultant@seita.nl", 200),
        # Has no consultant role.
        ("test_consultancy_user_without_consultant_access@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_get_one_user_audit_log_consultant(
    client, setup_api_test_data, requesting_user, status_code
):
    """Check correctness of consultant account audit log access rules"""
    test_user_account_id = find_user_by_email(
        "test_consultant_client@seita.nl"
    ).account.id

    get_account_response = client.get(
        url_for("AccountAPI:auditlog", id=test_user_account_id),
    )
    print("Server responded with:\n%s" % get_account_response.data)
    assert get_account_response.status_code == status_code
    if status_code == 200:
        assert get_account_response.json[0] is not None


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_consultant@seita.nl", 401),
    ],
    indirect=["requesting_user"],
)
def test_consultant_cannot_update_account_consultant(
    db,
    client,
    setup_api_test_data,
    requesting_user,
    expected_status_code,
):
    client_accounts = requesting_user.account.consultancy_client_accounts
    test_user_account_id = client_accounts[0].id if client_accounts else None

    patch_account_response = client.patch(
        url_for("AccountAPI:patch", id=test_user_account_id),
        json={"consultancy_account_id": 3},
    )

    print("Server responded with:\n%s" % patch_account_response.data)
    print("Status code: %s" % patch_account_response.status_code)
    assert patch_account_response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_account_attributes(client, setup_api_test_data, requesting_user, db):
    """Check whether updating an account's attributes with valid JSON succeeds."""
    account_id = requesting_user.account_id
    new_attrs = {"integration_key": "abc123", "max_power_kw": 50}

    response = client.patch(
        url_for("AccountAPI:patch", id=account_id),
        json={"attributes": json.dumps(new_attrs)},
    )
    print(f"Response: {response.json}")
    assert response.status_code == 200
    assert response.json["id"] == account_id
    # attributes are returned as a JSON string in the schema
    stored = json.loads(response.json["attributes"])
    assert stored["integration_key"] == "abc123"
    assert stored["max_power_kw"] == 50


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_account_attributes_bad_json(
    client, setup_api_test_data, requesting_user
):
    """Check whether updating an account's attributes with invalid JSON fails with 422."""
    account_id = requesting_user.account_id

    response = client.patch(
        url_for("AccountAPI:patch", id=account_id),
        json={"attributes": "not valid json {{{"},
    )
    print(f"Response: {response.json}")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_account_attributes_empty_dict(
    client, setup_api_test_data, requesting_user, db
):
    """Check that an empty attributes dict can be stored."""
    account_id = requesting_user.account_id

    response = client.patch(
        url_for("AccountAPI:patch", id=account_id),
        json={"attributes": json.dumps({})},
    )
    assert response.status_code == 200
    assert json.loads(response.json["attributes"]) == {}


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_patch_account_attributes_with_consultancy(
    client, setup_api_test_data, requesting_user, db
):
    """Updating attributes on an account that has a consultancy_account_id must not
    return 'Invalid consultancy_account_id' when consultancy_account_id is not part
    of the PATCH body."""
    consultancy_client_account = find_user_by_email(
        "test_consultant_client@seita.nl"
    ).account
    assert consultancy_client_account.consultancy_account_id is not None

    new_attrs = {"key": "value"}
    response = client.patch(
        url_for("AccountAPI:patch", id=consultancy_client_account.id),
        json={"attributes": json.dumps(new_attrs)},
    )
    print(f"Response: {response.json}")
    assert response.status_code == 200
    stored = json.loads(response.json["attributes"])
    assert stored["key"] == "value"
    # consultancy_account_id must remain unchanged
    assert (
        response.json["consultancy_account_id"]
        == consultancy_client_account.consultancy_account_id
    )


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),
        ("test_prosumer_user@seita.nl", 403),
        ("test_admin_user@seita.nl", 201),
        ("test_consultant@seita.nl", 201),
        ("test_consultancy_user_without_consultant_access@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_post_account(client, setup_api_test_data, requesting_user, status_code, db):
    payload = {
        "name": f"Created Account {requesting_user.id if requesting_user else 'anon'}",
        "primary_color": "#1a3443",
        "secondary_color": "#f1a122",
    }

    response = client.post(url_for("AccountAPI:post"), json=payload)
    assert response.status_code == status_code

    if status_code == 201:
        created = db.session.execute(
            select(Account).filter_by(name=payload["name"])
        ).scalar_one_or_none()
        assert created is not None

        if requesting_user.has_role("consultant"):
            assert created.consultancy_account_id == requesting_user.account.id
        else:
            assert created.consultancy_account_id is None


@pytest.mark.parametrize(
    "requesting_user",
    ["test_consultant@seita.nl"],
    indirect=["requesting_user"],
)
def test_post_account_consultant_without_required_account_role_forbidden(
    client, setup_api_test_data, requesting_user, db
):

    role = db.session.execute(
        select(AccountRole).filter_by(name=CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE)
    ).scalar_one_or_none()
    assert role is not None

    requesting_user.account.account_roles = [
        r
        for r in requesting_user.account.account_roles
        if r.name != CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE
    ]
    db.session.commit()

    payload = {
        "name": "Consultant Forbidden Account",
        "primary_color": "#1a3443",
        "secondary_color": "#f1a122",
    }
    response = client.post(url_for("AccountAPI:post"), json=payload)
    assert response.status_code == 403
