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


def test_user_role_editor_shows_role_descriptions(client, as_admin):
    user = find_user_by_email("test_prosumer_user_2@seita.nl")
    response = client.get(url_for("UserCrudUI:get", id=user.id))
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert (
        '<option value="account-admin">account-admin — Admin for this account</option>'
        in html
    )
    assert '"account-admin": "Admin for this account"' in html
    assert (
        '<span data-bs-toggle="tooltip" title="Admin for this account" '
        'tabindex="0">account-admin</span>' in html
    )
    assert "Roles add permissions. Remove account-member" in html
    option_positions = [
        html.index(f'<option value="{role}">')
        for role in ("account-member", "account-admin", "consultant", "admin-reader")
    ]
    assert option_positions == sorted(option_positions)


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
    assert user_page.status_code == 200
    assert (
        f'data-user-id="{user2.id}" data-own-password="false"'.encode()
        in user_page.data
    )
    assert client.get(f"/users/reset_password_for/{user2.id}").status_code == 404


def test_user_audit_log_is_for_whoever_may_read_it(client, as_prosumer_user1):
    """The user audit log page follows the same rule as the API, so it names no user from another account."""
    own = find_user_by_email("test_prosumer_user@seita.nl", keep_in_session=False)
    other = find_user_by_email("test_dummy_user_3@seita.nl", keep_in_session=False)

    assert client.get(url_for("UserCrudUI:auditlog", id=own.id)).status_code == 200
    response = client.get(url_for("UserCrudUI:auditlog", id=other.id))
    assert response.status_code == 403
    assert other.username.encode() not in response.data
