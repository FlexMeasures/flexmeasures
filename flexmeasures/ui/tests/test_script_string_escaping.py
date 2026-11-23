"""Values placed in inline scripts are JSON-encoded, so a backslash or quote in them cannot break the script."""

from flask import url_for

from flexmeasures.data.services.users import find_user_by_email


def test_user_page_encodes_user_fields_in_its_script(
    db, client, as_admin, setup_accounts
):
    user = find_user_by_email("test_prosumer_user_2@seita.nl")
    original_username = user.username
    user.username = "Trailing backslash \\"
    db.session.commit()
    try:
        response = client.get(
            url_for("UserCrudUI:get", id=user.id), follow_redirects=True
        )
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert 'username: "Trailing backslash \\\\"' in page
        assert "username: 'Trailing backslash \\'" not in page
    finally:
        user = find_user_by_email("test_prosumer_user_2@seita.nl")
        user.username = original_username
        db.session.commit()
