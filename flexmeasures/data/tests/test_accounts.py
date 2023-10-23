from flexmeasures.data.services.accounts import (
    get_accounts,
    get_number_of_assets_in_account,
    get_account_roles,
    get_consultant_client_accounts,
)
from flexmeasures.data.models.user import Account


def test_get_accounts(db, setup_assets):
    no_accounts = get_accounts("Not-an-existing-role")
    assert len(no_accounts) == 0
    dummy_accounts = get_accounts("Dummy")
    assert len(dummy_accounts) == 2  # Dummy and Multi-Role
    assert dummy_accounts[0].name == "Test Dummy Account"


def test_get_number_of_assets_in_account(db, setup_assets):
    """Get the number of assets in the testing accounts"""
    assert get_number_of_assets_in_account(1) == 3
    assert get_number_of_assets_in_account(2) == 0
    assert get_number_of_assets_in_account(3) == 0


def test_get_account_roles(db, setup_assets):
    """Get the account roles"""
    assert get_account_roles(1)[0].name == "Prosumer"
    assert get_account_roles(2)[0].name == "Supplier"
    assert get_account_roles(3)[0].name == "Dummy"
    assert get_account_roles(4) == []
    assert get_account_roles(9999999) == []  # non-existing account id
    multiple_roles = get_account_roles(5)
    assert [i.name for i in multiple_roles] == ["Prosumer", "Supplier", "Dummy"]


def test_get_consultant_client_accounts():
    consultant_account = Account.query.filter(
        Account.name == "Test Consultant Account"
    ).one_or_none()

    accounts = get_consultant_client_accounts(consultant_account.id)
    print(accounts)
    assert accounts[0]["name"] == "Test ConsultantClient Account"
