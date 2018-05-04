from flask import url_for

from bvp.tests.utils import logout


def test_dashboard_exists(app, use_auth, client):
    dashboard = client.get(url_for("bvp_ui.dashboard_view"), follow_redirects=True)
    assert dashboard.status_code == 200
    assert b"Status of my assets" in dashboard.data


def test_dashboard_exists_only_for_logged_in_users(app, use_auth, client):
    logout(client)
    dashboard = client.get(url_for("bvp_ui.dashboard_view"), follow_redirects=True)
    assert b"Please log in" in dashboard.data


def test_portfolio_exists(app, use_auth, client):
    portfolio = client.get(url_for("bvp_ui.portfolio_view"), follow_redirects=True)
    assert portfolio.status_code == 200
    assert b"Portfolio status" in portfolio.data


def test_control_exists(app, use_auth, client):
    control = client.get(url_for("bvp_ui.control_view"), follow_redirects=True)
    assert control.status_code == 200
    assert b"Control actions" in control.data


def test_logout(app, use_auth, client):
    logout_response = logout(client)
    assert b"Please log in" in logout_response.data


""" TODO https://trello.com/c/GjsWgLOE/226-load-docs-in-bvpui-and-put-it-inside-based-template
def test_docs_exists(app, authable, client):
    login(client, "wind@seita.nl", "wind")
    dashboard = client.get(url_for("bvp_ui.docs_view"), follow_redirects=True)
    assert dashboard.status_code == 200
    assert b"Control actions" in dashboard.data
"""