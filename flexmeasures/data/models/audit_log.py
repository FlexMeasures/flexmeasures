from __future__ import annotations

from flask_security import current_user
from sqlalchemy import DateTime, Column, Integer, String, ForeignKey

from flexmeasures.auth.policy import AuthModelMixin
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import User, Account
from flexmeasures.utils.time_utils import server_now


def get_current_user_id_name():
    current_user_id, current_user_name = None, None
    if (
        current_user
        and hasattr(current_user, "is_authenticated")
        and current_user.is_authenticated
    ):
        current_user_id, current_user_name = current_user.id, current_user.username
    return current_user_id, current_user_name


class AuditLog(db.Model, AuthModelMixin):
    """
    Model for storing actions that happen to user and tenant accounts
    E.g user creation, password reset etc.
    """

    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    event_datetime = Column(DateTime())
    event = Column(String(255))
    active_user_name = Column(String(255))
    active_user_id = Column(
        "active_user_id", Integer(), ForeignKey("fm_user.id", ondelete="SET NULL")
    )
    affected_user_id = Column(
        "affected_user_id", Integer(), ForeignKey("fm_user.id", ondelete="SET NULL")
    )
    affected_account_id = Column(
        "affected_account_id", Integer(), ForeignKey("account.id", ondelete="SET NULL")
    )

    @classmethod
    def user_table_acl(cls, user: User):
        """
        Table-level access rules for user-affecting audit logs. Use directly in check_access or in @permission_required_for_context with pass_ctx_to_loader, ctx_loader=AuditLog.user_acl.
        Permissions:
            User can see his own audit logs.
            Account-admin users can see audit logs for all users of their account.
            Admins / admin-readers can see audit logs for all users.
            Consultant users can see the audit log of all users in the client accounts.
        """

        class AuditLogAccess(AuthModelMixin):
            def __init__(self, user: User):
                if user:
                    self.user_id = user.id
                    self.account_id = user.account_id
                    self.consultancy_account_id = user.account.consultancy_account_id

            def __acl__(self):
                if not self.user_id:
                    return {}
                return {
                    "read": [
                        f"user:{self.user_id}",
                        (f"account:{self.account_id}", "role:account-admin"),
                        (f"account:{self.consultancy_account_id}", "role:consultant"),
                    ],
                }

        return AuditLogAccess(user)

    @classmethod
    def account_table_acl(cls, account: Account):
        """
        Table-level access rules for account-affecting audit logs. Use directly in check_access or in @permission_required_for_context with pass_ctx_to_loader, ctx_loader=AuditLog.user_acl.
        Permissions:
            Account-admin users can see audit logs for their account.
            Admins / admin-readers can see audit logs for all accounts.
            Consultant users can see the audit log of all client accounts.
        """

        class AuditLogAccess(AuthModelMixin):
            def __init__(self, account: Account):
                if account:
                    self.account_id = account.id
                    self.consultancy_account_id = account.consultancy_account_id

            def __acl__(self):
                if not self.account_id:
                    return {}
                return {
                    "read": [
                        (f"account:{self.account_id}", "role:account-admin"),
                        (f"account:{self.consultancy_account_id}", "role:consultant"),
                    ],
                }

        return AuditLogAccess(account)


class AssetAuditLog(db.Model, AuthModelMixin):
    """
    Model for storing actions that happen to an asset.
    E.g asset creation, editing etc.
    """

    __tablename__ = "asset_audit_log"
    id = Column(Integer, primary_key=True)
    event_datetime = Column(DateTime())
    event = Column(String(255))
    active_user_name = Column(String(255))
    active_user_id = Column(
        "active_user_id", Integer(), ForeignKey("fm_user.id", ondelete="SET NULL")
    )
    affected_asset_id = Column(
        "affected_asset_id",
        Integer(),
        ForeignKey("generic_asset.id", ondelete="SET NULL"),
    )

    @classmethod
    def add_record_for_attribute_update(
        cls,
        attribute_key: str,
        attribute_value: float | int | bool | str | list | dict | None,
        entity_type: str,
        asset_or_sensor: GenericAsset | Sensor,
    ) -> None:
        """Add audit log record about asset or sensor attribute update.

        :param attribute_key: attribute key to update
        :param attribute_value: new attribute value
        :param entity_type: 'asset' or 'sensor'
        :param asset_or_sensor: asset or sensor object
        """
        current_user_id, current_user_name = get_current_user_id_name()

        old_value = asset_or_sensor.attributes.get(attribute_key)
        if entity_type == "sensor":
            event = f"Updated sensor '{asset_or_sensor.name}': {asset_or_sensor.id}; "
            affected_asset_id = (asset_or_sensor.generic_asset_id,)
        else:
            event = f"Updated asset '{asset_or_sensor.name}': {asset_or_sensor.id}; "
            affected_asset_id = asset_or_sensor.id
        event += f"Attr '{attribute_key}' To {attribute_value} From {old_value}"

        audit_log = cls(
            event_datetime=server_now(),
            event=truncate_string(
                event, 255
            ),  # we truncate the event string if it 255 characters by adding ellipses in the middle
            active_user_id=current_user_id,
            active_user_name=current_user_name,
            affected_asset_id=affected_asset_id,
        )
        db.session.add(audit_log)

    @classmethod
    def add_record(
        cls,
        asset: GenericAsset | Sensor,
        event: str,
    ) -> None:
        """Add audit log record about asset related crud actions.

        :param asset: asset or sensor object
        :param event: event to log
        """
        current_user_id, current_user_name = get_current_user_id_name()

        audit_log = AssetAuditLog(
            event_datetime=server_now(),
            event=truncate_string(
                event, 255
            ),  # we truncate the event string if it exceed 255 characters by adding ellipses in the middle
            active_user_id=current_user_id,
            active_user_name=current_user_name,
            affected_asset_id=asset.id,
        )
        db.session.add(audit_log)


def truncate_string(value: str, max_length: int) -> str:
    """Truncate a string and add ellipses in the middle if it exceeds max_length."""
    if len(value) <= max_length:
        return value
    half_length = (max_length - 5) // 2
    return f"{value[:half_length]} ... {value[-half_length:]}"
