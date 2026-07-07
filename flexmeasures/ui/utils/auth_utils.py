from __future__ import annotations

from flask_login import current_user

from flexmeasures import Account
from flexmeasures.auth.policy import check_access, AuthModelMixin


def user_can_create_assets(account: Account | None = None) -> bool:
    if account is None:
        account = current_user.account
    try:
        check_access(account, "create-children")
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
        check_access(context, "delete")
    except Exception:
        return False
    return True


def user_can_update(context: AuthModelMixin) -> bool:
    try:
        check_access(context, "update")
    except Exception:
        return False
    return True
