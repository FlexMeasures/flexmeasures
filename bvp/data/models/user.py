from datetime import datetime

from flask_security import UserMixin, RoleMixin
from sqlalchemy.orm import relationship, backref
from sqlalchemy import Boolean, DateTime, Column, Integer, String, ForeignKey
from sqlalchemy.ext.hybrid import hybrid_property

from bvp.data.config import db


class RolesUsers(db.Model):
    __tablename__ = "bvp_roles_users"
    id = Column(Integer(), primary_key=True)
    user_id = Column("user_id", Integer(), ForeignKey("bvp_users.id"))
    role_id = Column("role_id", Integer(), ForeignKey("bvp_roles.id"))


class Role(db.Model, RoleMixin):
    __tablename__ = "bvp_roles"
    id = Column(Integer(), primary_key=True)
    name = Column(String(80), unique=True)
    description = Column(String(255))

    def __repr__(self):
        return "<Role:%s (ID:%d)>" % (self.description, self.id)


class User(db.Model, UserMixin):
    __tablename__ = "bvp_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
    username = Column(String(255), unique=True)
    password = Column(String(255))
    last_login_at = Column(DateTime())
    login_count = Column(Integer)
    active = Column(Boolean())
    timezone = Column(String(255), default="Europe/Amsterdam")
    bvp_roles = relationship(
        "Role", secondary="bvp_roles_users", backref=backref("users", lazy="dynamic")
    )

    def __repr__(self):
        return "<User %s (ID:%d)" % (self.username, self.id)

    @property
    def is_authenticated(self):
        """We are overloading this, so it also considers being active.
        Inactive users can by definition not be authenticated."""
        return super(UserMixin, self).is_authenticated and self.active

    @hybrid_property
    def roles(self):
        """The roles attribute is being used by Flask-Security in the @roles_required decorator (among others).
           With this little overload fix, it will only return the user's roles if they are authenticated.
           We do this to prevent that if a user is logged in while the admin deactivates them, their session would still work.
           In effect, we strip unauthenticated users from their roles. To read roles of an unauthenticated user
           (e.g. being inactive), use the `bvp_roles` attribute.
           If our auth model has moved to an improved way, e.g. requiring modern tokens, we should consider relaxing this.
           Note: This needed to become a hybrid property when moving to Flask-Security 3.4
        """
        if not self.is_authenticated and self is not User:
            return []
        else:
            return self.bvp_roles

    @roles.setter
    def roles(self, new_roles):
        """See comment in roles property why we overload."""
        self.bvp_roles = new_roles

    def has_role(self, role):
        """Returns `True` if the user identifies with the specified role.
            Overwritten from flask_security.core.UserMixin.

        :param role: A role name or `Role` instance"""
        if isinstance(role, str):
            return role in (role.name for role in self.bvp_roles)
        else:
            return role in self.bvp_roles


def remember_login(the_app, user):
    """We do not use the tracking feature of flask_security, but this basic meta data are quite handy to know"""
    user.last_login_at = datetime.utcnow()
    if user.login_count is None:
        user.login_count = 0
    user.login_count = user.login_count + 1
