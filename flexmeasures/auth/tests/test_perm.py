from werkzeug.exceptions import Forbidden, Unauthorized
from sqlalchemy import select
import flask_login.utils
import pytest

from flexmeasures.auth.policy import check_access
from flexmeasures.data.models.user import User


@pytest.mark.parametrize(
    "requesting_user, requested_user, required_perm, has_perm",
    [
        # Consultant tries to update client user
        ("test_consultant@seita.nl", "test_consultant_client@seita.nl", "update", True),
        # Consultant tries to update user from another client
        (
            "test_consultant@seita.nl",
            "test_admin_reader_user@seita.nl",
            "update",
            False,
        ),
    ],
)
def test_consultant_user_update_perm(
    db,
    monkeypatch,
    setup_roles_users,
    requesting_user,
    requested_user,
    required_perm,
    has_perm,
):

    requesting_user = db.session.execute(
        select(User).filter_by(email=requesting_user)
    ).scalar_one_or_none()

    requested_user = db.session.execute(
        select(User).filter_by(email=requested_user)
    ).scalar_one_or_none()

    monkeypatch.setattr(flask_login.utils, "_get_user", lambda: requesting_user)

    try:
        result = check_access(requested_user, required_perm)
        if result is None:
            has_access = True
    except (Forbidden, Unauthorized):
        has_access = False

    assert has_access == has_perm
