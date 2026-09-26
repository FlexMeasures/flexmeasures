import pytest

from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.utils import POSTGRES_INTEGER_MAX, get_by_id


@pytest.mark.parametrize(
    "account_id",
    [POSTGRES_INTEGER_MAX + 1, 8171766575, -POSTGRES_INTEGER_MAX - 2],
)
def test_get_by_id_finds_nothing_for_ids_beyond_an_integer_column(db, account_id):
    """An id that no integer column can hold matches nothing, rather than making the database refuse the query."""
    assert get_by_id(Account, account_id) is None


def test_get_by_id_finds_an_existing_model(db, setup_accounts):
    account = setup_accounts["Prosumer"]
    assert get_by_id(Account, account.id) is account
