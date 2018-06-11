from flask import url_for


def login(the_client, email, password):
    auth_data = dict(email=email, password=password)
    login_response = the_client.post(
        url_for("security.login"), data=auth_data, follow_redirects=True
    )
    assert login_response.status_code == 200
    assert b"Please log in" not in login_response.data
    return login_response


def logout(client):
    return client.get(url_for("security.logout"), follow_redirects=True)
