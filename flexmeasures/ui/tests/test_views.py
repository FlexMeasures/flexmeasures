from flask import url_for

from flexmeasures.ui.tests.utils import logout


def test_dashboard_responds(client, setup_assets, as_prosumer_user1):
    dashboard = client.get(
        url_for("flexmeasures_ui.dashboard_view"), follow_redirects=True
    )
    assert dashboard.status_code == 200
    assert b"Dashboard" in dashboard.data


def test_dashboard_responds_only_for_logged_in_users(client, as_prosumer_user1):
    logout(client)
    dashboard = client.get(
        url_for("flexmeasures_ui.dashboard_view"), follow_redirects=True
    )
    assert b"Please log in" in dashboard.data


def test_assets_responds(client, requests_mock, as_prosumer_user1):
    requests_mock.get(
        "http://localhost//api/v3_0/assets",
        status_code=200,
        json=[],
    )
    requests_mock.get(
        "http://localhost//api/v3_0/assets/public",
        status_code=200,
        json=[],
    )
    assets_page = client.get(url_for("AssetCrudUI:index"), follow_redirects=True)
    assert assets_page.status_code == 200
    assert b"Asset overview" in assets_page.data


def test_logout(client, as_prosumer_user1):
    logout_response = logout(client)
    assert b"Please log in" in logout_response.data


def test_logged_in_user_page_breadcrumb(client, as_prosumer_user1):
    """The logged-in user overview page should show account and username in a breadcrumb."""
    from flask_login import current_user

    page = client.get(
        url_for("flexmeasures_ui.logged_in_user_view"), follow_redirects=True
    )
    assert page.status_code == 200
    assert b'aria-label="breadcrumb' in page.data
    assert current_user.account.name.encode() in page.data
    assert current_user.username.encode() in page.data


def test_dashboard_keeps_asset_names_out_of_script(
    db, client, setup_accounts, setup_generic_asset_types, as_admin
):
    """Asset and account names land in the map popups and tooltips as JSON strings, never as raw text in the script.

    The popup is a JS template literal, so a raw name with ${...} or a backtick would run as code,
    and the popup and tooltip are set as HTML, so the strings hold HTML-escaped text.
    """
    import re

    from flexmeasures.data.models.generic_assets import GenericAsset

    marker = "${alert(1)}"
    asset = GenericAsset(
        name=f"Site {marker} `x` <img src=x onerror=alert(2)>",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        latitude=52.1,
        longitude=5.1,
    )
    db.session.add(asset)
    db.session.commit()
    try:
        dashboard = client.get(url_for("flexmeasures_ui.dashboard_view"))
        assert dashboard.status_code == 200
        page = dashboard.data.decode()
        lines_with_name = [line for line in page.splitlines() if marker in line]
        assert len(lines_with_name) >= 2  # the popup and the tooltip
        for line in lines_with_name:
            # Each occurrence of the name is inside a double-quoted JSON string on that line.
            assert re.search(r'"[^"]*' + re.escape(marker) + r'[^"]*"', line), line
        # The markup in the name is HTML-escaped before it is JSON-encoded (tojson writes & as &).
        assert "<img src=x" not in page
        assert "\\u0026lt;img src=x" in page
    finally:
        db.session.delete(asset)
        db.session.commit()
