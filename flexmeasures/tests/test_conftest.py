from flask import g

# Listed here rather than imported from flexmeasures.conftest, so that shrinking the tuple over there fails these tests instead of silently narrowing them.
CACHED_AUTH_STATE_KEYS = ("_login_user", "fs_authn_via", "fs_paa", "csrf_valid")


def test_login_cache_is_set_for_previous_test(app):
    """Model a test that leaves flask-login's user cache populated."""
    with app.test_request_context("/"):
        for key in CACHED_AUTH_STATE_KEYS:
            setattr(g, key, object())

    # The request context above shares the session-scoped app context's `g`, which is exactly why this state can leak.
    # Assert that here, so this pair of tests cannot go vacuous: if the state stopped surviving the request context, the next test would pass without testing anything.
    for key in CACHED_AUTH_STATE_KEYS:
        assert key in g, f"{key} did not survive the request context"


def test_login_cache_is_cleared_after_previous_test(app):
    """A later test must start without the previous test's cached user."""
    for key in CACHED_AUTH_STATE_KEYS:
        assert key not in g, f"{key} leaked from the previous test"
