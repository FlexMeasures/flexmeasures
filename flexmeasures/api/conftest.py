import pytest

from flask_login import login_user, logout_user

from flexmeasures.api.tests.utils import UserContext


@pytest.fixture
def requesting_user(request):
    """Use this fixture to log in a user for the scope of a test.

    Sets the user by passing it an email address (see usage examples below), or pass None to get the AnonymousUser.
    Passes the user object to the test.
    Logs the user out after the test ran.

    Usage:

    >>> @pytest.mark.parametrize("requesting_user", ["test_prosumer_user_2@seita.nl", None], indirect=True)

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
    email = request.param
    if email is not None:
        with UserContext(email) as user:
            login_user(user)
            yield user
            logout_user()
    else:
        yield
