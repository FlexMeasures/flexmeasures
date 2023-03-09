from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account


def get_number_of_assets_in_account(account_id: int):
    """Get the number of assets in an account."""
    number_of_assets_in_account = GenericAsset.query.filter(
        GenericAsset.account_id == account_id
    ).count()
    return number_of_assets_in_account


def get_account_roles(account_id: int):
    account = Account.query.filter_by(id=account_id).one_or_none()
    if account.account_roles:
        account_roles = f"{', '.join([role.name for role in account.account_roles])}"
    else:
        account_roles = None
    return account_roles
