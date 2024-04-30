from __future__ import annotations

from sqlalchemy import DateTime, Column, Integer, String, ForeignKey

from flexmeasures.data import db
from flexmeasures.data.models.user import User, Account
from flexmeasures.auth.policy import AuthModelMixin


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
