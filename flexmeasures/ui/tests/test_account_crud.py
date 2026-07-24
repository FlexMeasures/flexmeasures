import pytest

from flask import url_for
from flask_login import current_user
from sqlalchemy import select

from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import AccountRole
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.auth.policy import CONSULTANCY_ACCOUNT_ROLE
from flexmeasures.utils.time_utils import server_now

from flexmeasures.ui.tests.utils import login, logout

account_api_path = "http://localhost//api/v3_0/accounts"


@pytest.fixture
def as_dummy_user3(client):
    """Login a plain user from the Dummy account (different from Prosumer or Supplier)."""
    login(client, "test_dummy_user_3@seita.nl", "testtest")
    yield
    logout(client)


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
        select(AccountRole).filter_by(name=CONSULTANCY_ACCOUNT_ROLE)
    ).scalar_one_or_none()
    if role is None:
        role = AccountRole(
            name=CONSULTANCY_ACCOUNT_ROLE,
            description="Consultancy account that can create own client accounts",
        )
        db.session.add(role)
        db.session.flush()

    has_role = consultant_account.has_role(CONSULTANCY_ACCOUNT_ROLE)
    if enable and not has_role:
        consultant_account.account_roles.append(role)
    if not enable and has_role:
        consultant_account.account_roles = [
            r
            for r in consultant_account.account_roles
            if r.name != CONSULTANCY_ACCOUNT_ROLE
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


def test_accounts_index_role_filter_lists_accessible_roles(db, client, as_admin):
    account_page = client.get(url_for("AccountCrudUI:index"), follow_redirects=True)

    assert account_page.status_code == 200
    assert b'id="accountRoleFilter"' in account_page.data
    assert b"Organisation role" in account_page.data
    assert b'<option value="">All roles</option>' in account_page.data
    assert b'<option value="Prosumer">Prosumer</option>' in account_page.data
    assert b'<option value="Supplier">Supplier</option>' in account_page.data
    assert b"role=${encodeURIComponent(selectedRole)}" in account_page.data
    assert b"table.api().ajax.reload()" in account_page.data


def test_accounts_index_role_filter_hides_inaccessible_roles(
    db, client, as_prosumer_user1
):
    account_page = client.get(url_for("AccountCrudUI:index"), follow_redirects=True)

    assert account_page.status_code == 200
    assert b'<option value="Prosumer">Prosumer</option>' in account_page.data
    assert b'<option value="Supplier">Supplier</option>' not in account_page.data


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


def test_create_account_page_shows_default_consultancy_for_non_admin(
    db, client, as_consultant
):
    _set_consultant_account_role(db, True)

    response = client.get(url_for("AccountCrudUI:new"), follow_redirects=True)

    assert response.status_code == 200
    assert b"Consultancy account" in response.data
    assert b"Test Consultancy Account" in response.data
    assert b"The new account will be linked as a client account" in response.data


def test_account_page_add_client_account_button_for_consultancy_account(
    db, client, as_consultant
):
    _set_consultant_account_role(db, True)
    consultancy_account_id = find_user_by_email("test_consultant@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=consultancy_account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    assert b"Add client account" in account_page.data


def test_account_page_no_add_client_account_button_for_client_account(
    db, client, as_consultant
):
    _set_consultant_account_role(db, True)
    client_account_id = find_user_by_email("test_consultant_client@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=client_account_id),
        follow_redirects=True,
    )

    assert account_page.status_code == 200
    assert b"Add client account" not in account_page.data


def test_account_page_shows_consultancy_account_for_client_account(
    db, client, as_consultant
):
    client_account_id = find_user_by_email("test_consultant_client@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=client_account_id),
        follow_redirects=True,
    )

    assert account_page.status_code == 200
    assert b"Consultancy" in account_page.data
    assert b"Test Consultancy Account" in account_page.data


def test_account_page_lists_client_accounts_for_consultancy_account(
    db, client, as_consultant
):
    consultancy_account_id = find_user_by_email("test_consultant@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=consultancy_account_id),
        follow_redirects=True,
    )

    assert account_page.status_code == 200
    assert b"Client accounts" in account_page.data
    assert b"Test ConsultancyClient Account" in account_page.data


def test_account_page_shows_no_client_accounts_for_non_consultancy_account(
    db, client, as_prosumer_user1
):
    account_id = find_user_by_email("test_prosumer_user@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=account_id),
        follow_redirects=True,
    )

    assert account_page.status_code == 200
    assert b"Client accounts" in account_page.data
    assert b"None" in account_page.data


def test_account_page_no_add_client_account_button_for_non_consultancy_account(
    db, client, as_consultant
):
    _set_consultant_account_role(db, False)
    non_consultancy_account_id = find_user_by_email(
        "test_consultant@seita.nl"
    ).account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=non_consultancy_account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    assert b"Add client account" not in account_page.data


def test_account_page_add_client_account_button_for_site_admin(db, client, as_admin):
    account_id = find_user_by_email("test_prosumer_user@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    assert b"Add client account" in account_page.data


def test_account_page_account_roles_are_editable_for_site_admin(db, client, as_admin):
    account_id = find_user_by_email("test_prosumer_user@seita.nl").account.id

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=account_id),
        follow_redirects=True,
    )

    assert account_page.status_code == 200
    assert b'id="account_roles"' in account_page.data
    assert b'name="account_roles"' in account_page.data
    assert b"Prosumer" in account_page.data


def test_account_audit_log_shows_acting_user_name_and_id(db, client, as_admin):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    audit_log = AuditLog(
        event_datetime=server_now(),
        event="Test account audit event",
        active_user_id=user.id,
        active_user_name=user.username,
        affected_account_id=user.account.id,
    )
    db.session.add(audit_log)
    db.session.commit()

    audit_log_page = client.get(
        url_for("AccountCrudUI:auditlog", account_id=user.account.id),
        follow_redirects=True,
    )

    assert audit_log_page.status_code == 200
    assert b"Acting User" in audit_log_page.data
    assert f"{user.username} (Id: {user.id})".encode() in audit_log_page.data


def test_account_page_forbidden_for_different_account_user(
    db, client, setup_accounts, as_dummy_user3
):
    """A user from the Dummy account must not be able to view the Prosumer account page.

    ``AccountCrudUI.get`` calls ``check_access(account, "read")``, which blocks
    users who are not members of the requested account.
    """
    prosumer_account = setup_accounts["Prosumer"]

    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=prosumer_account.id),
        follow_redirects=True,
    )
    assert account_page.status_code == 403
