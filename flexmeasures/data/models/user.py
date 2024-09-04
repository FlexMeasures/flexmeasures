from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import datetime

from flask_security import UserMixin, RoleMixin
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import relationship, backref
from sqlalchemy import Boolean, DateTime, Column, Integer, String, ForeignKey
from sqlalchemy.ext.hybrid import hybrid_property
from timely_beliefs import utils as tb_utils

from flexmeasures.data import db
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
    to_annotation_frame,
)
from flexmeasures.data.models.parsing_utils import parse_source_arg
from flexmeasures.auth.policy import AuthModelMixin

if TYPE_CHECKING:
    from flexmeasures.data.models.data_sources import DataSource


class RolesAccounts(db.Model):
    __tablename__ = "roles_accounts"
    id = Column(Integer(), primary_key=True)
    account_id = Column("account_id", Integer(), ForeignKey("account.id"))
    role_id = Column("role_id", Integer(), ForeignKey("account_role.id"))
    __table_args__ = (
        db.UniqueConstraint(
            "role_id",
            "account_id",
            name="roles_accounts_role_id_key",
        ),
    )


class AccountRole(db.Model):
    __tablename__ = "account_role"
    id = Column(Integer(), primary_key=True)
    name = Column(String(80), unique=True)
    description = Column(String(255))

    def __repr__(self):
        return "<AccountRole:%s (ID:%s)>" % (self.name, self.id)


class Account(db.Model, AuthModelMixin):
    """
    Account of a tenant on the server.
    Bundles Users as well as GenericAssets.
    """

    __tablename__ = "account"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), default="", unique=True)
    account_roles = relationship(
        "AccountRole",
        secondary="roles_accounts",
        backref=backref("accounts", lazy="dynamic"),
    )
    primary_color = Column(String(7), default=None)
    secondary_color = Column(String(7), default=None)
    logo_url = Column(String(255), default=None)
    annotations = db.relationship(
        "Annotation",
        secondary="annotations_accounts",
        backref=db.backref("accounts", lazy="dynamic"),
    )

    # Setup self-referential relationship between consultancy account and consultancy client account
    consultancy_account_id = Column(
        Integer, db.ForeignKey("account.id"), default=None, nullable=True
    )
    consultancy_client_accounts = db.relationship(
        "Account", back_populates="consultancy_account"
    )
    consultancy_account = db.relationship(
        "Account", back_populates="consultancy_client_accounts", remote_side=[id]
    )

    def __repr__(self):
        return "<Account %s (ID:%s)>" % (self.name, self.id)

    def __acl__(self):
        """
        Only account admins can create things in the account (e.g. users or assets).
        Consultants (i.e. users with the consultant role) can read things in the account,
        but only if their organisation is set as a consultancy for the given account.
        Within same account, everyone can read and update.
        Creation and deletion of accounts are left to site admins in CLI.
        """

        read_access = [f"account:{self.id}"]
        if self.consultancy_account_id is not None:
            read_access.append(
                (f"account:{self.consultancy_account_id}", "role:consultant")
            )
        return {
            "create-children": (f"account:{self.id}", "role:account-admin"),
            "read": read_access,
            "update": f"account:{self.id}",
        }

    def get_path(self, separator: str = ">"):
        return self.name

    def has_role(self, role: str | AccountRole) -> bool:
        """Returns `True` if the account has the specified role.

        :param role: An account role name or `AccountRole` instance"""
        if isinstance(role, str):
            return role in (role.name for role in self.account_roles)
        else:
            return role in self.account_roles

    def search_annotations(
        self,
        annotation_starts_after: datetime | None = None,  # deprecated
        annotations_after: datetime | None = None,
        annotation_ends_before: datetime | None = None,  # deprecated
        annotations_before: datetime | None = None,
        source: (
            DataSource | list[DataSource] | int | list[int] | str | list[str] | None
        ) = None,
        as_frame: bool = False,
    ) -> list[Annotation] | pd.DataFrame:
        """Return annotations assigned to this account.

        :param annotations_after: only return annotations that end after this datetime (exclusive)
        :param annotations_before: only return annotations that start before this datetime (exclusive)
        """

        # todo: deprecate the 'annotation_starts_after' argument in favor of 'annotations_after' (announced v0.11.0)
        annotations_after = tb_utils.replace_deprecated_argument(
            "annotation_starts_after",
            annotation_starts_after,
            "annotations_after",
            annotations_after,
            required_argument=False,
        )

        # todo: deprecate the 'annotation_ends_before' argument in favor of 'annotations_before' (announced v0.11.0)
        annotations_before = tb_utils.replace_deprecated_argument(
            "annotation_ends_before",
            annotation_ends_before,
            "annotations_before",
            annotations_before,
            required_argument=False,
        )

        parsed_sources = parse_source_arg(source)
        query = (
            select(Annotation)
            .join(AccountAnnotationRelationship)
            .filter(
                AccountAnnotationRelationship.account_id == self.id,
                AccountAnnotationRelationship.annotation_id == Annotation.id,
            )
        )
        if annotations_after is not None:
            query = query.filter(
                Annotation.end > annotations_after,
            )
        if annotations_before is not None:
            query = query.filter(
                Annotation.start < annotations_before,
            )
        if parsed_sources:
            query = query.filter(
                Annotation.source.in_(parsed_sources),
            )
        annotations = db.session.scalars(query).all()

        return to_annotation_frame(annotations) if as_frame else annotations

    @property
    def number_of_assets(self):
        from flexmeasures.data.models.generic_assets import GenericAsset

        return db.session.execute(
            select(func.count()).where(GenericAsset.account_id == self.id)
        ).scalar_one_or_none()

    @property
    def number_of_users(self):
        return db.session.execute(
            select(func.count()).where(User.account_id == self.id)
        ).scalar_one_or_none()


class RolesUsers(db.Model):
    __tablename__ = "roles_users"
    id = Column(Integer(), primary_key=True)
    user_id = Column("user_id", Integer(), ForeignKey("fm_user.id"))
    role_id = Column("role_id", Integer(), ForeignKey("role.id"))
    __table_args__ = (
        db.UniqueConstraint(
            "role_id",
            "user_id",
            name="roles_users_role_id_key",
        ),
    )


class Role(db.Model, RoleMixin):
    __tablename__ = "role"
    id = Column(Integer(), primary_key=True)
    name = Column(String(80), unique=True)
    description = Column(String(255))

    def __repr__(self):
        return "<Role:%s (ID:%s)>" % (self.name, self.id)


class User(db.Model, UserMixin, AuthModelMixin):
    """
    We use the flask security UserMixin, which does include functionality,
    but not the fields (those are in flask_security/models::FsUserMixin).
    We went with a pick&choose approach. This gives us more freedom, e.g.
    to choose our own table name or add logic around the activation status.
    If we add new FS functionality (e.g. 2FA), the fields needed for that
    need to be added here.
    """

    __tablename__ = "fm_user"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
    username = Column(String(255), unique=True)
    password = Column(String(255))
    # Last time the user logged in (provided credentials to get access)
    last_login_at = Column(DateTime())
    # Last time the user made a request (authorized by session or auth token)
    last_seen_at = Column(DateTime())
    # How often have they logged in?
    login_count = Column(Integer)
    active = Column(Boolean())
    # Faster token checking
    fs_uniquifier = Column(String(64), unique=True, nullable=False)
    timezone = Column(String(255), default="Europe/Amsterdam")
    account_id = Column(Integer, db.ForeignKey("account.id"), nullable=False)

    account = db.relationship("Account", backref=db.backref("users", lazy=True))
    flexmeasures_roles = relationship(
        "Role",
        secondary="roles_users",
        backref=backref("users", lazy="dynamic"),
    )

    def __repr__(self):
        return "<User %s (ID:%s)>" % (self.username, self.id)

    def __acl__(self):
        """
        Within same account, everyone can read.
        Only the user themselves or account-admins can edit their user record.
        Creation and deletion are left to site admins in CLI.
        """
        return {
            "read": f"account:{self.account_id}",
            "update": [
                f"user:{self.id}",
                (f"account:{self.account_id}", "role:account-admin"),
            ],
        }

    @property
    def is_authenticated(self) -> bool:
        """We are overloading this, so it also considers being active.
        Inactive users can by definition not be authenticated."""
        return super(UserMixin, self).is_authenticated and self.active

    @hybrid_property
    def roles(self):
        """The roles attribute is being used by Flask-Security in the @roles_required decorator (among others).
        With this little overload fix, it will only return the user's roles if they are authenticated.
        We do this to prevent that if a user is logged in while the admin deactivates them, their session would still work.
        In effect, we strip unauthenticated users from their roles. To read roles of an unauthenticated user
        (e.g. being inactive), use the `flexmeasures_roles` attribute.
        If our auth model has moved to an improved way, e.g. requiring modern tokens, we should consider relaxing this.
        Note: This needed to become a hybrid property when moving to Flask-Security 3.4
        """
        if not self.is_authenticated and self is not User:
            return []
        else:
            return self.flexmeasures_roles

    @roles.setter
    def roles(self, new_roles):
        """See comment in roles property why we overload."""
        self.flexmeasures_roles = new_roles

    def has_role(self, role: str | Role) -> bool:
        """Returns `True` if the user identifies with the specified role.
            Overwritten from flask_security.core.UserMixin.

        :param role: A role name or `Role` instance"""
        if isinstance(role, str):
            return role in (role.name for role in self.flexmeasures_roles)
        else:
            return role in self.flexmeasures_roles


def remember_login(the_app, user):
    """We do not use the tracking feature of flask_security, but this basic meta data are quite handy to know"""
    user.last_login_at = datetime.utcnow()
    if user.login_count is None:
        user.login_count = 0
    user.login_count = user.login_count + 1


def remember_last_seen(user):
    """Update the last_seen field"""
    if user is not None and user.is_authenticated:
        user.last_seen_at = datetime.utcnow()
        db.session.add(user)
        db.session.commit()


def is_user(o) -> bool:
    """True if object is or proxies a User, False otherwise.

    Takes into account that object can be of LocalProxy type, and
    uses get_current_object to get the underlying (User) object.
    """
    return isinstance(o, User) or (
        hasattr(o, "_get_current_object") and isinstance(o._get_current_object(), User)
    )
