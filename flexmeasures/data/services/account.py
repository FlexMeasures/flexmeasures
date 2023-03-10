from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account, AccountRole


def get_number_of_assets_in_account(account_id: int) -> int:
    """Get the number of assets in an account."""
    number_of_assets_in_account = GenericAsset.query.filter(
        GenericAsset.account_id == account_id
    ).count()
    return number_of_assets_in_account


def get_account_roles(account_id: int) -> AccountRole:
    account = Account.query.filter_by(id=account_id).one_or_none()
if account is None:
    return []
    account_roles = account.account_roles
    return account_roles
