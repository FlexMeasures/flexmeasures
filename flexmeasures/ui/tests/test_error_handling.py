import pytest
import json

from flexmeasures.auth import error_handling as auth_error_handling

"""
Testing if errors are handled by the right handlers.
First, test a JSON request, then a common one, which should lead to a rendered page.

With Gone we are also testing an HTTPException which we currently do not explicitly support, so no explicit rendering
of our base template. I was hoping registering for HTTPException would do this, but it does not.

We also test unauth handling, whether flask security raises in its own way or we raise ourselves.
"""


@pytest.mark.parametrize(
    "raising_url,status_code,expected_message",
    [
        ("/raise-error?type=server_error", 500, "InternalServerError Test Message"),
        ("/raise-error?type=bad_request", 400, "BadRequest Test Message"),
        ("/raise-error?type=gone", 410, "Gone Test Message"),
        ("/raise-error?type=unauthorized", 401, auth_error_handling.UNAUTH_MSG),
        ("/raise-error?type=forbidden", 403, auth_error_handling.FORBIDDEN_MSG),
        ("/non-existant-endpoint", 404, None),
        ("/protected-endpoint-only-for-admins", 403, auth_error_handling.FORBIDDEN_MSG),
    ],
)
def test_error_handling(
    client, error_endpoints, raising_url, status_code, expected_message
):
    """
    Make requests and check if the error comes back as expected.
    Try json as well as html content types.
    """
    res = client.get(raising_url, headers={"Content-Type": "application/json"})
    assert res.status_code == status_code
    assert "application/json" in res.content_type
    if expected_message:
        assert expected_message in json.loads(res.data)["message"]

    res = client.get(raising_url, headers={"Content-Type": "text/html"})
    print(f"Server responded with {res.data}")
    assert res.status_code == status_code
    assert "text/html" in res.content_type
    # test if we rendered the base template
    assert b"- FlexMeasures" in res.data
    if expected_message:
        assert expected_message.encode() in res.data


def test_unhandled_error_is_an_internal_server_error(client, error_endpoints):
    """An exception that is not an HTTPException becomes a proper 500 response, in JSON as well as in HTML.

    SQLAlchemy errors carry a code like "f405", which once made it into the status line ("0 f405"),
    so browsers behind a proxy reported a protocol error instead of showing our error page.
    Also, the SQL and its parameters belong in the logs, not in the response.
    """
    raising_url = "/raise-error?type=database_error"
    generic_message = "The server encountered an internal error"

    res = client.get(raising_url, headers={"Content-Type": "text/html"})
    assert res.status == "500 INTERNAL SERVER ERROR"
    assert b"- FlexMeasures" in res.data
    assert generic_message.encode() in res.data
    assert b"SELECT secret" not in res.data

    res = client.get(raising_url, headers={"Content-Type": "application/json"})
    assert res.status == "500 INTERNAL SERVER ERROR"
    assert generic_message in json.loads(res.data)["message"]
    assert b"SELECT secret" not in res.data
