"""Regression tests for code-defined grants and their ACL scope."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flexmeasures.auth.policy import (
    ACCOUNT_ADMIN_ROLE,
    ADMIN_READER_ROLE,
    ADMIN_ROLE,
    CONSULTANT_ROLE,
    INTEGRATION_ROLE,
    MEMBER_ROLE,
    READ_ONLY_ROLE,
    user_has_scoped_permission,
)
from flexmeasures.data.models.user import Role
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor


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
    assert "reset-password" not in Role(name=READ_ONLY_ROLE).permissions


def test_new_permission_is_not_granted_to_existing_roles(monkeypatch):
    from flexmeasures.auth import policy

    monkeypatch.setattr(policy, "PERMISSIONS", (*policy.PERMISSIONS, "future-action"))
    for name in (
        READ_ONLY_ROLE,
        INTEGRATION_ROLE,
        MEMBER_ROLE,
        ACCOUNT_ADMIN_ROLE,
        CONSULTANT_ROLE,
        ADMIN_READER_ROLE,
        ADMIN_ROLE,
    ):
        assert "future-action" not in Role(name=name).permissions


def test_named_asset_and_sensor_acls_keep_existing_scopes():
    owner = SimpleNamespace(
        consultancy_account_id=20,
        __acl__=lambda: {"read": ["account:10"]},
    )
    asset = SimpleNamespace(account_id=10, owner=owner)
    asset_acl = GenericAsset.__acl__(asset)

    assert asset_acl["edit-assets"] == asset_acl["update"]
    assert asset_acl["edit-sensors"] == asset_acl["create-children"]
    assert asset_acl["delete-data"] == asset_acl["delete"]
    assert asset_acl["delete-data"] == [
        ("account:10", f"role:{ACCOUNT_ADMIN_ROLE}"),
        ("account:20", f"role:{CONSULTANT_ROLE}"),
    ]

    asset.__acl__ = lambda: asset_acl
    sensor_acl = Sensor.__acl__(SimpleNamespace(generic_asset=asset))
    assert sensor_acl["post-data"] == sensor_acl["create-children"]
    assert sensor_acl["edit-sensors"] == sensor_acl["update"]
    assert sensor_acl["delete-data"] == sensor_acl["delete"]
