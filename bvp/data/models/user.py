from datetime import datetime

from flask_security import UserMixin, RoleMixin
from sqlalchemy.orm import relationship, backref
from sqlalchemy import Boolean, DateTime, Column, Integer, String, ForeignKey

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


class User(db.Model, UserMixin):
    __tablename__ = "bvp_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
    username = Column(String(255))
    password = Column(String(255))
    last_login_at = Column(DateTime())
    login_count = Column(Integer)
    active = Column(Boolean())
    timezone = Column(String(255), default="Europe/Amsterdam")
    roles = relationship(
        "Role", secondary="bvp_roles_users", backref=backref("users", lazy="dynamic")
    )


def remember_login(the_app, user):
    """We do not use the tracking feature of flask_security, but this basic meta data are quite handy to know"""
    user.last_login_at = datetime.utcnow()
    if user.login_count is None:
        user.login_count = 0
    user.login_count = user.login_count + 1
    the_app.security.datastore.commit()
