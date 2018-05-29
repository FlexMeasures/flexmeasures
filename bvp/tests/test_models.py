import bvp.data.models


def test_resolutions():
    assert len(bvp.data.models.resolutions) == 4


def test_users(app):
    # TODO: importing before the app fixture is executed fails as db is still None. We might be able to do better.
    from bvp.data.models.user import User
    users = User.query.all()
    assert len(users) > 0