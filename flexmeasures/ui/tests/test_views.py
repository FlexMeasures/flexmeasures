from flask import url_for
from flask_security import SQLAlchemySessionUserDatastore

from flexmeasures.ui.tests.utils import logout


def test_dashboard_responds(client, as_prosumer):
    dashboard = client.get(
        url_for("flexmeasures_ui.dashboard_view"), follow_redirects=True
    )
    assert dashboard.status_code == 200
    assert b"This dashboard shows you" in dashboard.data
    assert b"Status of my assets" in dashboard.data


def test_dashboard_responds_only_for_logged_in_users(client, as_prosumer):
    logout(client)
    dashboard = client.get(
        url_for("flexmeasures_ui.dashboard_view"), follow_redirects=True
    )
    assert b"Please log in" in dashboard.data


def test_portfolio_responds(client, as_prosumer):
    portfolio = client.get(
        url_for("flexmeasures_ui.portfolio_view"), follow_redirects=True
    )
    assert portfolio.status_code == 200
    assert b"Portfolio status" in portfolio.data


def test_assets_responds(client, requests_mock, as_prosumer):
    requests_mock.get("http://localhost//api/v2_0/assets", status_code=200, json={})
    assets_page = client.get(url_for("AssetCrudUI:index"), follow_redirects=True)
    assert assets_page.status_code == 200
    assert b"All assets" in assets_page.data


def test_control_responds(client, as_prosumer):
    control = client.get(url_for("flexmeasures_ui.control_view"), follow_redirects=True)
    assert control.status_code == 200
    assert b"Control actions" in control.data


def test_analytics_responds(db, client, as_prosumer):
    analytics = client.get(
        url_for("flexmeasures_ui.analytics_view"), follow_redirects=True
    )
    assert analytics.status_code == 200
    assert b"Client analytics" in analytics.data

    from flexmeasures.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")

    assert str.encode(f"for {test_prosumer.username}") in analytics.data


def test_logout(client, as_prosumer):
    logout_response = logout(client)
    assert b"Please log in" in logout_response.data


""" TODO https://trello.com/c/GjsWgLOE/226-load-docs-in-bvpui-and-put-it-inside-based-template
def test_docs_responds(app, authable, client):
    login(client, "wind@seita.nl", "wind")
    dashboard = client.get(url_for("flexmeasures_ui.docs_view"), follow_redirects=True)
    assert dashboard.status_code == 200
    assert b"Control actions" in dashboard.data
"""
