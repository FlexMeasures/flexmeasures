"""The password reset form needs new passwords of at least 12 characters."""

from flask import url_for
from flask_security.recoverable import generate_reset_password_token
from flask_security.utils import verify_password

from flexmeasures.data.services.users import find_user_by_email


def test_reset_password_form_requires_a_long_enough_password(
    app, db, client, setup_roles_users
):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    token = generate_reset_password_token(user)
    response = client.post(
        url_for("security.reset_password", token=token),
        data=dict(password="elevenchars", password_confirm="elevenchars"),
    )
    assert "at least 12 characters" in response.get_data(as_text=True)
    db.session.expire_all()
    user = find_user_by_email("test_prosumer_user@seita.nl")
    assert verify_password("testtest", user.password)
