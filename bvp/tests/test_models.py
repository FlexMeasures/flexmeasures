import pytest
from flask import url_for

import bvp.models


def test_resolutions():
    assert len(bvp.models.resolutions) == 4


def test_users(app):
    # TODO: importing before the app fixture is executed fails as db is still None. We might be able to do better.
    from bvp.models.user import User
    users = User.query.all()
    assert len(users) > 0