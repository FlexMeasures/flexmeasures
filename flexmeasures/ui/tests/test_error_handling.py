import pytest
import json

from flexmeasures.data import auth_setup


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
        ("/raise-error?type=unauthorized", 401, auth_setup.UNAUTH_MSG),
        ("/raise-error?type=forbidden", 403, auth_setup.FORBIDDEN_MSG),
        ("/non-existant-endpoint", 404, None),
        ("/protected-endpoint-only-for-admins", 403, auth_setup.FORBIDDEN_MSG),
    ],
)
def test_error_handling(
    client, error_endpoints, raising_url, status_code, expected_message
):
    res = client.get(raising_url, headers={"Content-Type": "application/json"})
    assert res.status_code == status_code
    assert "application/json" in res.content_type
    if expected_message:
        assert json.loads(res.data)["message"] == expected_message

    res = client.get(raising_url)
    print(f"Server responded with {res.data}")
    assert res.status_code == status_code
    assert "text/html" in res.content_type
    # test if we rendered the base template
    assert b"- FlexMeasures" in res.data
    if expected_message:
        assert expected_message.encode() in res.data
