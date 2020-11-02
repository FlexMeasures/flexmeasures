from flask import url_for, request
from bvp.data.services.users import find_user_by_email


def test_user_crud_as_non_admin(client, as_prosumer):
    user_index = client.get(url_for("UserCrud:index"), follow_redirects=True)
    assert user_index.status_code == 403
    prosumer2_id = find_user_by_email("test_prosumer2@seita.nl").id
    user_page = client.get(
        url_for("UserCrud:get", id=prosumer2_id), follow_redirects=True
    )
    assert user_page.status_code == 403
    user_page = client.get(
        url_for("UserCrud:toggle_active", id=prosumer2_id), follow_redirects=True
    )
    assert user_page.status_code == 403
    user_page = client.get(
        url_for("UserCrud:delete_with_data", id=prosumer2_id), follow_redirects=True
    )
    assert user_page.status_code == 403
    user_page = client.get(
        url_for("UserCrud:reset_password_for", id=prosumer2_id), follow_redirects=True
    )
    assert user_page.status_code == 403


def test_user_list(client, as_admin):
    user_index = client.get(url_for("UserCrud:index"), follow_redirects=True)
    assert user_index.status_code == 200
    assert b"All active users" in user_index.data
    assert b"test_prosumer@seita.nl" in user_index.data
    assert b"test_prosumer2@seita.nl" in user_index.data


def test_user_page(client, as_admin):
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl", keep_in_session=False)
    user_page = client.get(
        url_for("UserCrud:get", id=prosumer2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert ("Account overview for %s" % prosumer2.username).encode() in user_page.data
    assert prosumer2.email.encode() in user_page.data


def test_deactivate_user(client, as_admin):
    """Switch prosumer2 to inactive, check user index, and re-activate him/her."""
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl", keep_in_session=False)
    # de-activate
    user_page = client.get(
        url_for("UserCrud:toggle_active", id=prosumer2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert find_user_by_email("test_prosumer2@seita.nl").active is False
    assert b"new activation status is now False" in user_page.data
    # check index
    user_index = client.get(url_for("UserCrud:index"), follow_redirects=True)
    assert user_index.status_code == 200
    assert b"All active users" in user_index.data
    assert b"test_prosumer@seita.nl" in user_index.data
    assert b"test_prosumer2@seita.nl" not in user_index.data
    user_index = client.get(
        url_for("UserCrud:index") + "?include_inactive=on", follow_redirects=True
    )
    assert user_index.status_code == 200
    assert b"All users" in user_index.data
    assert b"test_prosumer2@seita.nl" in user_index.data
    # re-activate
    user_page = client.get(
        url_for("UserCrud:toggle_active", id=prosumer2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert b"new activation status is now True" in user_page.data
    user_index = client.get(
        url_for("UserCrud:index", id=prosumer2.id), follow_redirects=True
    )
    assert user_index.status_code == 200
    assert b"test_prosumer2@seita.nl" in user_index.data


def test_delete_user(client, as_admin):
    """ Test that deletion does not fail, test that user is not in list anymore"""
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl", keep_in_session=False)
    user_page = client.get(
        url_for("UserCrud:delete_with_data", id=prosumer2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert b"have been deleted" in user_page.data
    user_index = client.get(url_for("UserCrud:index"), follow_redirects=True)
    assert user_index.status_code == 200
    assert b"test_prosumer2@seita.nl" not in user_index.data


def test_reset_password(app, client, as_admin):
    """Test it does not fail, test that user password has changed and they got a reset email"""
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl", keep_in_session=False)
    old_password = prosumer2.password
    with app.mail.record_messages() as outbox:
        user_page = client.get(
            url_for("UserCrud:reset_password_for", id=prosumer2.id),
            follow_redirects=True,
        )
        assert len(outbox) == 2
        assert "has been reset" in outbox[0].subject
        assert "reset instructions" in outbox[1].subject
        assert "reset your password:\n\n%sreset/" % request.host_url in outbox[1].body
    assert user_page.status_code == 200
    assert b"has been changed to a random password" in user_page.data
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl")
    assert old_password != prosumer2.password
