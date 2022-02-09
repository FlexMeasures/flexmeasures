import pytest
from typing import Dict

from flexmeasures.auth.policy import ADMIN_ROLE
from flexmeasures.data.services.users import create_user, User


@pytest.fixture(scope="module")
def setup_account_owner(db, setup_accounts) -> Dict[str, User]:
    account_owner = create_user(
        username="Test Account Owner",
        email="test_account_owner@seita.nl",
        account_name=setup_accounts["Prosumer"].name,
        password="testtest",
        # TODO: change ADMIN_ROLE to ACCOUNT_ADMIN
        user_roles=dict(
            name=ADMIN_ROLE, description="A user who can do everything."
        ),
    )
    return {account_owner.username: account_owner}
