from flask import url_for
from flask_login import current_user
import pytest
from sqlalchemy import select

from flexmeasures.data.models.user import AccountRole
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.auth.policy import CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE


account_api_path = "http://localhost//api/v3_0/accounts"


def test_account_page(db, client, as_prosumer_user1):
    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=current_user.account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    assert str(f"Account: {current_user.account.name}") in str(account_page.data)
    assert b"All users" in account_page.data
    assert str(current_user.username) in str(account_page.data)


def test_account_page_breadcrumb(db, client, as_prosumer_user1):
    """Account page should show the account name in a breadcrumb."""
    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=current_user.account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    # Breadcrumb nav should be present
    assert b'aria-label="breadcrumb' in account_page.data
    # Account name should appear in the breadcrumb
    assert current_user.account.name.encode() in account_page.data


def _set_consultant_account_role(db, enable: bool):
    consultant_account = find_user_by_email("test_consultant@seita.nl").account
    role = db.session.execute(
        select(AccountRole).filter_by(name=CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE)
    ).scalar_one_or_none()
    if role is None:
        role = AccountRole(
            name=CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE,
            description="Consultancy account that can create own client accounts",
        )
        db.session.add(role)
        db.session.flush()

    has_role = consultant_account.has_role(CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE)
    if enable and not has_role:
        consultant_account.account_roles.append(role)
    if not enable and has_role:
        consultant_account.account_roles = [
            r
            for r in consultant_account.account_roles
            if r.name != CONSULTANT_WITH_OWN_CLIENTS_ACCOUNT_ROLE
        ]
    db.session.commit()


@pytest.mark.parametrize(
    "login_fixture, consultant_account_role_enabled, expect_create_button",
    [
        ("as_admin", True, True),
        ("as_consultant", True, True),
        ("as_consultant", False, False),
        ("as_prosumer_user1", True, False),
    ],
)
def test_accounts_index_create_account_button_visibility(
    db,
    client,
    request,
    login_fixture,
    consultant_account_role_enabled,
    expect_create_button,
):
    _set_consultant_account_role(db, consultant_account_role_enabled)
    request.getfixturevalue(login_fixture)

    account_page = client.get(url_for("AccountCrudUI:index"), follow_redirects=True)
    assert account_page.status_code == 200
    if expect_create_button:
        assert b"Create account" in account_page.data
    else:
        assert b"Create account" not in account_page.data


@pytest.mark.parametrize(
    "login_fixture, consultant_account_role_enabled, expected_status_code",
    [
        ("as_admin", True, 200),
        ("as_consultant", True, 200),
        ("as_consultant", False, 403),
        ("as_prosumer_user1", True, 403),
    ],
)
def test_create_account_page_access_control(
    db,
    client,
    request,
    login_fixture,
    consultant_account_role_enabled,
    expected_status_code,
):
    _set_consultant_account_role(db, consultant_account_role_enabled)
    request.getfixturevalue(login_fixture)

    response = client.get(url_for("AccountCrudUI:new"), follow_redirects=True)
    assert response.status_code == expected_status_code
