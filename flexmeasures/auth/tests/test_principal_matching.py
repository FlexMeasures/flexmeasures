from __future__ import annotations

import pytest

from flexmeasures.auth.policy import user_matches_principals, can_modify_role


class MockAccount:

    id: int
    account_roles: list[str]

    def __init__(self, id, roles, consultancy_account=None):
        self.id = id
        self.account_roles = roles
        self.consultancy_account = consultancy_account

    def has_role(self, role):
        return role in self.account_roles


class MockUser:

    id: int
    roles: list[str]
    account: MockAccount

    def __init__(self, id, username, roles, account):
        self.id = id
        self.username = username
        self.roles = roles
        self.account = account

    def has_role(self, role):
        return role in self.roles


def make_mock_user(
    user_id: int,
    user_roles: list[str],
    account_id: int,
    account_roles: list[str],
    consultancy_account_id: int | None = None,
) -> MockUser:
    consultancy_account = None
    if consultancy_account_id is not None:
        consultancy_account = MockAccount(consultancy_account_id, [], None)
    account = MockAccount(account_id, account_roles, consultancy_account)
    return MockUser(id=user_id, username="Tester", roles=user_roles, account=account)


@pytest.mark.parametrize(
    "mock_user,principals,should_match",
    [
        # atomic principals (one item needs to match)
        (make_mock_user(19, [], 1, []), "user:19", True),
        (make_mock_user(19, [], 1, []), "user:28", False),
        (make_mock_user(19, ["gardener"], 1, []), "role:gardener", True),
        # principals with >1 items (as a tuple)
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
        # more than one principal (as a list)
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
        # finally, testing that empty principals are not accepted
        (
            make_mock_user(19, ["waitress"], 113, ["restaurant"]),
            (),
            False,
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["restaurant"]),
            [],
            False,
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["restaurant"]),
            None,
            False,
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["restaurant"]),
            "",
            False,
        ),
        (
            make_mock_user(19, ["waitress"], 113, ["restaurant"]),
            [(), "role:waitress"],
            True,
        ),
    ],
)
def test_principals_match(mock_user, principals, should_match):
    assert user_matches_principals(mock_user, principals) == should_match


@pytest.mark.parametrize(
    "mock_user, modified_user, roles_to_modify, can_modify_roles",
    [
        # Admin user should be able to modify (admin-reader & consultant) roles
        (
            make_mock_user(19, ["admin"], 1, []),
            make_mock_user(20, ["admin-reader", "consultant"], 1, []),
            [3, 4],
            True,
        ),
        # Consultant user should not be able to modify (admin-reader) role
        (
            make_mock_user(19, ["consultant"], 1, []),
            make_mock_user(21, ["admin-reader"], 1, []),
            [3],
            False,
        ),
        # Admin-reader user should not be able to modify (admin-reader) role
        (
            make_mock_user(19, ["admin-reader"], 1, []),
            make_mock_user(22, ["admin-reader"], 1, []),
            [3],
            False,
        ),
        # Account-admin user should not be able to modify (admin-reader) role
        (
            make_mock_user(19, ["account-admin"], 1, []),
            make_mock_user(23, ["admin-reader"], 1, []),
            [3],
            False,
        ),
        # Account-admin user should be able to modify (consultant) role
        (
            make_mock_user(18, ["account-admin"], 4, []),
            make_mock_user(24, ["consultant"], 4, []),
            [4],
            True,
        ),
        # Account-admin user should not be able to modify (consultant) role of another account
        (
            make_mock_user(17, ["account-admin"], 1, []),
            make_mock_user(25, ["consultant"], 2, []),
            [4],
            False,
        ),
        # Consultant user should be able to modify (account-admin) role of the accoumt its consulting
        (
            make_mock_user(19, ["consultant"], 1, []),
            make_mock_user(26, ["account-admin"], 2, [], 1),
            [1],
            True,
        ),
    ],
)
def test_can_modify_role(
    db, setup_roles_users, mock_user, roles_to_modify, can_modify_roles, modified_user
):
    assert (
        can_modify_role(mock_user, roles_to_modify, modified_user) == can_modify_roles
    )
