"""Regression tests for code-defined grants and their ACL scope."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flexmeasures.auth.policy import (
    ACCOUNT_ADMIN_ROLE,
    CONSULTANT_ROLE,
    INTEGRATION_ROLE,
    MEMBER_ROLE,
    READ_ONLY_ROLE,
    user_has_scoped_permission,
)
from flexmeasures.data.models.user import Role


@pytest.mark.parametrize(
    "role_name, allowed, denied",
    [
        (READ_ONLY_ROLE, "read", "post-data"),
        (INTEGRATION_ROLE, "post-data", "edit-assets"),
        (MEMBER_ROLE, "edit-assets", "delete-data"),
        (ACCOUNT_ADMIN_ROLE, "delete-data", None),
        (CONSULTANT_ROLE, "delete-data", None),
        ("unrecognized-role", None, "read"),
    ],
)
def test_role_permissions_are_defined_by_role_name(role_name, allowed, denied):
    grants = Role(name=role_name).permissions

    assert isinstance(grants, frozenset)
    if allowed is not None:
        assert allowed in grants
    if denied is not None:
        assert denied not in grants


class ScopedUser:
    def __init__(self, roles):
        self.id = 1
        self.account = SimpleNamespace(id=10, has_role=lambda role: False)
        self.roles = [
            SimpleNamespace(name=name, permissions=permissions)
            for name, permissions in roles
        ]

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles)


def test_consultant_grant_does_not_apply_to_home_account():
    user = ScopedUser(
        [
            (MEMBER_ROLE, frozenset({"read"})),
            (CONSULTANT_ROLE, frozenset({"edit-account"})),
        ]
    )

    assert not user_has_scoped_permission(user, "edit-account", "account:10")
    assert user_has_scoped_permission(
        user, "edit-account", ("account:10", f"role:{CONSULTANT_ROLE}")
    )


def test_home_member_grant_does_not_apply_to_client_account():
    user = ScopedUser(
        [
            (MEMBER_ROLE, frozenset({"annotate"})),
            (CONSULTANT_ROLE, frozenset({"read"})),
        ]
    )

    assert user_has_scoped_permission(user, "annotate", "account:10")
    assert not user_has_scoped_permission(
        user, "annotate", ("account:10", f"role:{CONSULTANT_ROLE}")
    )


def test_read_only_role_can_match_read_acl_but_not_mutation_acl():
    user = ScopedUser([(READ_ONLY_ROLE, Role(name=READ_ONLY_ROLE).permissions)])

    assert user_has_scoped_permission(user, "read", "account:10")
    assert not user_has_scoped_permission(user, "edit-assets", "account:10")
    assert not user_has_scoped_permission(user, "post-data", "account:10")
