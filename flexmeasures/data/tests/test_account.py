from flexmeasures.data.services.account import (
    get_number_of_assets_in_account,
    get_account_roles,
)


def test_get_number_of_assets_in_account(db, setup_assets):
    """Get the number of assets in the testing accounts"""
    assert get_number_of_assets_in_account(1) == 3
    assert get_number_of_assets_in_account(2) == 0
    assert get_number_of_assets_in_account(3) == 0


def test_get_account_roles(db):
    """Get the account roles"""
    assert get_account_roles(1) == "Prosumer"
    assert get_account_roles(2) == "Supplier"
    assert get_account_roles(3) == "Dummy"
    assert get_account_roles(4) is None
    assert get_account_roles(5) == "Prosumer, Supplier, Dummy"
