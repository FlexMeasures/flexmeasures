from __future__ import annotations

from flask_login import current_user

from flexmeasures import Account
from flexmeasures.auth.policy import check_access, AuthModelMixin


def user_can_access(context: AuthModelMixin, permission: str) -> bool:
    """Return whether the current user has a named permission on a resource."""
    try:
        check_access(context, permission)
    except Exception:
        return False
    return True


def user_can_create_assets(account: Account | None = None) -> bool:
    if account is None:
        account = current_user.account
    try:
        check_access(account, "edit-assets")
    except Exception:
        return False
    return True


def user_can_create_children(context: AuthModelMixin) -> bool:
    try:
        check_access(context, "create-children")
    except Exception:
        return False
    return True


def user_can_delete(context: AuthModelMixin) -> bool:
    try:
        from flexmeasures.data.models.generic_assets import GenericAsset
        from flexmeasures.data.models.time_series import Sensor
        from flexmeasures.data.services.generic_assets import asset_contains_data
        from flexmeasures.data.services.sensors import sensor_contains_data

        if isinstance(context, GenericAsset):
            check_access(context, "edit-assets")
            if asset_contains_data(context, lock=False):
                check_access(context, "delete-data")
        elif isinstance(context, Sensor):
            check_access(context.generic_asset, "edit-sensors")
            if sensor_contains_data(context, lock=False):
                check_access(context, "delete-data")
        else:
            check_access(context, "delete")
    except Exception:
        return False
    return True


def user_can_read(context: AuthModelMixin) -> bool:
    try:
        check_access(context, "read")
    except Exception:
        return False
    return True


def user_can_update(context: AuthModelMixin) -> bool:
    try:
        from flexmeasures.data.models.generic_assets import GenericAsset
        from flexmeasures.data.models.time_series import Sensor

        if isinstance(context, GenericAsset):
            check_access(context, "edit-assets")
        elif isinstance(context, Sensor):
            check_access(context, "edit-sensors")
        elif isinstance(context, Account):
            check_access(context, "edit-account")
        else:
            check_access(context, "update")
    except Exception:
        return False
    return True
