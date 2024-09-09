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


def test_control_responds(client, as_prosumer_user1):
    control = client.get(url_for("flexmeasures_ui.control_view"), follow_redirects=True)
    assert control.status_code == 200
    assert b"Control actions" in control.data


def test_logout(client, as_prosumer_user1):
    logout_response = logout(client)
    assert b"Please log in" in logout_response.data
