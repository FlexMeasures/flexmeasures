import pytest

from flask import url_for
from flask_login import current_user

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
