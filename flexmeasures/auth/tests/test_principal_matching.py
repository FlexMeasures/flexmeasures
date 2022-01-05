from typing import List

import pytest

from flexmeasures.auth.policy import user_matches_principals


class MockAccount:

    id: int
    account_roles: List[str]

    def __init__(self, id, roles):
        self.id = id
        self.account_roles = roles

    def has_role(self, role):
        return role in self.account_roles


class MockUser:

    id: int
    roles: List[str]
    account: MockAccount

    def __init__(self, id, username, roles, account):
        self.id = id
        self.username = username
        self.roles = roles
        self.account = account

    def has_role(self, role):
        return role in self.roles


def make_mock_user(
    user_id: int, user_roles: List[str], account_id: int, account_roles: List[str]
) -> MockUser:
    account = MockAccount(account_id, account_roles)
    return MockUser(id=user_id, username="Tester", roles=user_roles, account=account)


@pytest.mark.parametrize(
    "mock_user,principals,should_match",
    [
        (make_mock_user(19, [], 1, []), "user:19", True),
        (make_mock_user(19, [], 1, []), "user:28", False),
        (make_mock_user(19, ["gardener"], 1, []), "role:gardener", True),
        (
            make_mock_user(19, ["gardener"], 1, ["castle"]),
            ("role:gardener", "account-role:castle"),
            True,
        ),
        (
            make_mock_user(19, ["gardener"], 1, ["castle"]),
            ("role:gardener", "account-role:villa"),
            False,
        ),
        (make_mock_user(19, [], 113, []), "account:114", False),
        (make_mock_user(19, [], 113, []), "account:113", True),
        (
            make_mock_user(19, ["waitress"], 113, ["restaurant"]),
            ("user:19", "account:113", "role:waitress", "account-role:restaurant"),
            True,
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["hotel"]),
            ("user:13", "account:113", "role:waitress", "role:chef"),
            False,
        ),
        (
            make_mock_user(19, ["waitress", "chef"], 113, ["hotel", "cinema"]),
            (
                "user:19",
                "account:113",
                "role:waitress",
                "role:chef",
                "account-role:hotel",
                "account-role:cinema",
            ),
            True,
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["hotel"]),
            ["user:13", ("account:113", "role:waitress", "role:chef")],
            False,  # not user 13; well a waitress, but not also a chef of hotel 113
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["hotel"]),
            ["user:13", ("account:113", "role:waitress"), "role:chef"],
            True,  # not user 13; well a waitress of hotel 113 -
        ),
    ],
)
def test_principals_match(mock_user, principals, should_match):
    assert user_matches_principals(mock_user, principals) == should_match
