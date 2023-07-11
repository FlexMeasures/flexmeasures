import pytest

from flask import url_for


@pytest.mark.parametrize(
    "blueprint, api_version_being_sunset",
    [
        ("flexmeasures_api_v1", "1.0"),
        ("flexmeasures_api_v1_1", "1.1"),
        ("flexmeasures_api_v1_2", "1.2"),
        ("flexmeasures_api_v1_3", "1.3"),
        ("flexmeasures_api_v2_0", "2.0"),
    ],
)
def test_sunset(client, blueprint, api_version_being_sunset):
    gone = client.get(url_for(f"{blueprint}.implementation_gone"))
    assert gone.status_code == 410
    assert (
        f"API version {api_version_being_sunset} has been sunset"
        in gone.json["message"]
    )
