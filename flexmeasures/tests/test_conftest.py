def test_login_cache_is_set_for_previous_test(app):
    """Model a test that leaves flask-login's user cache populated."""
    from flask import g

    with app.test_request_context("/"):
        g._login_user = object()


def test_login_cache_is_cleared_after_previous_test(app):
    """A later test must start without the previous test's cached user."""
    from flask import g

    assert "_login_user" not in g
