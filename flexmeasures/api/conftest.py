import pytest
from pytest_mock import MockerFixture
from flask_login import login_user, logout_user
from flask_security import decorators as fs_decorators

from flexmeasures.api.tests.utils import UserContext, patched_check_token


@pytest.fixture(scope="function", autouse=True)
def patch_check_token(monkeypatch):
    """
    Patch Flask-Security's _check_token for all API tests.
    
    This is needed because Flask-Security's _check_token in Flask >2.2
    doesn't properly persist the user with flask_login during testing.
    Without this patch, API tests that use token authentication fail with 401.
    
    See: https://github.com/FlexMeasures/flexmeasures/issues/1298
    """
    monkeypatch.setattr(fs_decorators, "_check_token", patched_check_token)


@pytest.fixture
def requesting_user(request):
    """Use this fixture to log in a user for the scope of a test.

    Sets the user by passing it an email address (see usage examples below), or pass None to get the AnonymousUser.
    Passes the user object to the test.
    Logs the user out after the test ran.

    Usage:

    >>> @pytest.mark.parametrize("requesting_user", ["test_prosumer_user_2@seita.nl", None], indirect=True)
    ... def test_api_feature(requesting_user):
    ...     pass

    Or in combination with other parameters:

    @pytest.mark.parametrize(
        "requesting_user, status_code",
        [
            (None, 401),
            ("test_prosumer_user_2@seita.nl", 200),
        ],
        indirect=["requesting_user"],
    )

    """
    from flask_security.decorators import set_request_attr
    
    email = request.param
    if email is not None:
        with UserContext(email) as user:
            login_user(user)
            # Set fs_authn_via to "session" to indicate session-based authentication
            # This is needed for Flask-Security's _check_session to work properly
            set_request_attr("fs_authn_via", "session")
            yield user
            logout_user()
    else:
        yield


@pytest.fixture
def mock_get_statuses(mocker: MockerFixture):
    return mocker.patch(
        "flexmeasures.data.services.sensors.get_statuses", autospec=True
    )
