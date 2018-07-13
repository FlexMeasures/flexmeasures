from flask import url_for

from bvp.ui.tests.utils import logout


def test_dashboard_responds(client, use_auth):
    dashboard = client.get(url_for("bvp_ui.dashboard_view"), follow_redirects=True)
    assert dashboard.status_code == 200
    assert b"Status of my assets" in dashboard.data


def test_dashboard_responds_only_for_logged_in_users(client, use_auth):
    logout(client)
    dashboard = client.get(url_for("bvp_ui.dashboard_view"), follow_redirects=True)
    assert b"Please log in" in dashboard.data


def test_portfolio_responds(client, use_auth):
    portfolio = client.get(url_for("bvp_ui.portfolio_view"), follow_redirects=True)
    assert portfolio.status_code == 200
    assert b"Portfolio status" in portfolio.data


def test_assets_responds(client, use_auth):
    assets_page = client.get(
        url_for("bvp_ui.portfolio_view").replace("portfolio", "assets"),
        follow_redirects=True,
    )
    assert assets_page.status_code == 200
    assert b"All assets" in assets_page.data


def test_control_responds(client, use_auth):
    control = client.get(url_for("bvp_ui.control_view"), follow_redirects=True)
    assert control.status_code == 200
    assert b"Control actions" in control.data


def test_analytics_responds(client, use_auth):
    analytics = client.get(url_for("bvp_ui.analytics_view"), follow_redirects=True)
    assert analytics.status_code == 200
    assert b"Client analytics" in analytics.data
    assert b"for test_prosumer@seita.nl" in analytics.data


def test_logout(client, use_auth):
    logout_response = logout(client)
    assert b"Please log in" in logout_response.data


""" TODO https://trello.com/c/GjsWgLOE/226-load-docs-in-bvpui-and-put-it-inside-based-template
def test_docs_responds(app, authable, client):
    login(client, "wind@seita.nl", "wind")
    dashboard = client.get(url_for("bvp_ui.docs_view"), follow_redirects=True)
    assert dashboard.status_code == 200
    assert b"Control actions" in dashboard.data
"""
