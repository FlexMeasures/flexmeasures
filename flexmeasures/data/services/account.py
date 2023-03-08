from flexmeasures.data.models.generic_assets import GenericAsset


def get_number_of_assets_in_account(account_id: int):
    """Get the number of assets in an account."""
    number_of_assets_in_account = GenericAsset.query.filter(
        GenericAsset.account_id == account_id
    ).count()
    return number_of_assets_in_account
