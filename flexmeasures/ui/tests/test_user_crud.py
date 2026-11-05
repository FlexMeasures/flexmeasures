from flask import url_for

from flexmeasures.data.services.users import find_user_by_email

"""
Testing if the UI crud views do auth checks and display answers.
Actual logic is tested in the API tests.
"""


def test_user_list(client, as_admin):
    user_index = client.get(url_for("UserCrudUI:index"), follow_redirects=True)
    assert user_index.status_code == 200
    assert b"All active users" in user_index.data


def test_user_page_as_nonadmin_from_other_account(client, as_prosumer_user1):
    dummy_user_id = find_user_by_email("test_dummy_user_3@seita.nl").id
    user_page = client.get(
        url_for("UserCrudUI:get", id=dummy_user_id), follow_redirects=True
    )
    assert user_page.status_code == 403


def test_user_page(client, as_admin, setup_accounts):
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl")
    user_page = client.get(
        url_for("UserCrudUI:get", id=user2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert ("User: %s" % user2.username).encode() in user_page.data
    assert (f">{user2.account.number_of_assets}</a>").encode() in user_page.data
    assert user2.email.encode() in user_page.data


def test_user_page_breadcrumb(client, as_admin, setup_accounts):
    """User page should show account name and username in a breadcrumb."""
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl")
    user_page = client.get(
        url_for("UserCrudUI:get", id=user2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    # Breadcrumb nav should be present
    assert b'aria-label="breadcrumb' in user_page.data
    # Both account name and username should appear in the breadcrumb ancestors
    assert user2.account.name.encode() in user_page.data
    assert user2.username.encode() in user_page.data


def test_reset_password_button_resets_through_the_api(client, as_admin):
    """The reset button names the user whose password it resets through the API; a GET on a UI route no longer resets it.

    The reset itself is tested in the API tests.
    """
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl", keep_in_session=False)
    user_page = client.get(url_for("UserCrudUI:get", id=user2.id))
    assert user_page.status_code == 200, "An admin should see the user's page."
    assert (
        f'data-user-id="{user2.id}" data-own-password="false"'.encode()
        in user_page.data
    ), "The reset button should name the user, who is not the one logged in."
    assert (
        client.get(f"/users/reset_password_for/{user2.id}").status_code == 404
    ), "The UI route that reset passwords on a GET should be gone."


def test_user_audit_log_is_for_whoever_may_read_it(client, as_prosumer_user1):
    """The user audit log page follows the same rule as the API, so it names no user from another account."""
    own = find_user_by_email("test_prosumer_user@seita.nl", keep_in_session=False)
    other = find_user_by_email("test_dummy_user_3@seita.nl", keep_in_session=False)

    assert (
        client.get(url_for("UserCrudUI:auditlog", id=own.id)).status_code == 200
    ), "A user should see their own audit log page."
    response = client.get(url_for("UserCrudUI:auditlog", id=other.id))
    assert (
        response.status_code == 403
    ), "The audit log page of a user of another account should be forbidden."
    assert (
        other.username.encode() not in response.data
    ), "The other user's name should not be shown."
