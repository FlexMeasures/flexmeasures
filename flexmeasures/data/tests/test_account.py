from flexmeasures.data.services.account import get_number_of_assets_in_account


def test_get_number_of_assets_in_account(db, setup_assets):
    """Get the number of assets in the testing accounts"""
    assert get_number_of_assets_in_account(1) == 3
    assert get_number_of_assets_in_account(2) == 0
    assert get_number_of_assets_in_account(3) == 0
