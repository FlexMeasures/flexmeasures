import pytest

from flexmeasures.data.services.accounts import (
    get_accounts,
    get_number_of_assets_in_account,
    get_account_roles,
    create_account,
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


def test_new_account(app, db):
    account_name = "test_account"
    account_roles = ["account_role1", "account_role2"]
    create_account(account_name, account_roles)

    account = db.session.query(Account).filter_by(name=account_name).one_or_none()
    assert account.name == account_name


def test_new_account_no_roles(app, db):
    account_name = "test_account2"
    account_roles = []
    create_account(account_name, account_roles)
    account = db.session.query(Account).filter_by(name=account_name).one_or_none()
    assert account.name == account_name


def test_new_account_name_already_exists(app, db):
    account_name = "existing_account"
    account = Account(name=account_name)
    db.session.add(account)
    db.session.commit()
    account_roles = []
    with pytest.raises(ValueError):
        create_account(account_name, account_roles)
