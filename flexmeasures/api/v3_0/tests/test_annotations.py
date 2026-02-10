"""
Tests for the annotation API endpoints (under development).

These tests validate the three POST endpoints for creating annotations:
- POST /api/v3_0/accounts/<id>/annotations
- POST /api/v3_0/assets/<id>/annotations
- POST /api/v3_0/sensors/<id>/annotations
"""

from __future__ import annotations

import pytest
from flask import url_for
from sqlalchemy import select, func

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account
from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (
            "test_prosumer_user_2@seita.nl",
            201,
        ),  # account-admin can annotate own account
        ("test_admin_user@seita.nl", 201),  # admin can annotate any account
        ("test_prosumer_user@seita.nl", 403),  # regular user without admin role
        ("test_dummy_user_3@seita.nl", 403),  # user from different account
        (None, 401),  # no authentication
    ],
    indirect=["requesting_user"],
)
def test_post_account_annotation_permissions(
    client, setup_api_test_data, requesting_user, expected_status_code
):
    """Test permission validation for account annotations.

    Validates that:
    - Account admins can annotate their own account
    - Platform admins can annotate any account
    - Regular users without account-admin role cannot annotate
    - Users from different accounts cannot annotate
    - Unauthenticated requests are rejected
    """
    # Get the Prosumer account ID
    prosumer_account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Test annotation",
        "start": "2024-01-01T00:00:00+01:00",
        "end": "2024-01-01T01:00:00+01:00",
        "type": "label",
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=prosumer_account.id),
        json=annotation_data,
    )

    assert response.status_code == expected_status_code

    if expected_status_code == 201:
        # Verify response contains expected fields
        assert "id" in response.json
        assert response.json["content"] == "Test annotation"
        assert response.json["type"] == "label"
        assert "source_id" in response.json

        # Verify annotation is linked to account
        annotation = client.application.db.session.get(Annotation, response.json["id"])
        assert annotation in prosumer_account.annotations


@pytest.mark.parametrize(
    "requesting_user, asset_name, expected_status_code",
    [
        (
            "test_supplier_user_4@seita.nl",
            "incineration line",
            201,
        ),  # supplier owns the asset
        (
            "test_admin_user@seita.nl",
            "incineration line",
            201,
        ),  # admin can annotate any asset
        (
            "test_prosumer_user@seita.nl",
            "incineration line",
            403,
        ),  # user doesn't own asset
        (None, "incineration line", 401),  # no authentication
    ],
    indirect=["requesting_user"],
)
def test_post_asset_annotation_permissions(
    client, setup_api_test_data, requesting_user, asset_name, expected_status_code
):
    """Test permission validation for asset annotations.

    Validates that:
    - Asset owners can annotate their assets
    - Platform admins can annotate any asset
    - Users without ownership cannot annotate
    - Unauthenticated requests are rejected
    """
    # Get the incineration line asset
    asset = client.application.db.session.execute(
        select(GenericAsset).filter_by(name=asset_name)
    ).scalar_one()

    annotation_data = {
        "content": "Asset maintenance scheduled",
        "start": "2024-02-01T00:00:00+01:00",
        "end": "2024-02-01T02:00:00+01:00",
        "type": "alert",
    }

    response = client.post(
        url_for("AssetAPI:post_annotation", id=asset.id),
        json=annotation_data,
    )

    assert response.status_code == expected_status_code

    if expected_status_code == 201:
        # Verify response format
        assert "id" in response.json
        assert response.json["content"] == "Asset maintenance scheduled"
        assert response.json["type"] == "alert"

        # Verify annotation is linked to asset
        annotation = client.application.db.session.get(Annotation, response.json["id"])
        assert annotation in asset.annotations


@pytest.mark.parametrize(
    "requesting_user, sensor_name, expected_status_code",
    [
        (
            "test_supplier_user_4@seita.nl",
            "some gas sensor",
            201,
        ),  # supplier owns the sensor
        (
            "test_admin_user@seita.nl",
            "some gas sensor",
            201,
        ),  # admin can annotate any sensor
        (
            "test_prosumer_user@seita.nl",
            "some gas sensor",
            403,
        ),  # user doesn't own sensor
        (None, "some gas sensor", 401),  # no authentication
    ],
    indirect=["requesting_user"],
)
def test_post_sensor_annotation_permissions(
    client,
    setup_api_test_data,
    requesting_user,
    sensor_name,
    expected_status_code,
):
    """Test permission validation for sensor annotations.

    Validates that:
    - Sensor owners (via asset ownership) can annotate their sensors
    - Platform admins can annotate any sensor
    - Users without ownership cannot annotate
    - Unauthenticated requests are rejected
    """
    # Get the gas sensor
    sensor = client.application.db.session.execute(
        select(Sensor).filter_by(name=sensor_name)
    ).scalar_one()

    annotation_data = {
        "content": "Sensor calibration performed",
        "start": "2024-03-01T10:00:00+01:00",
        "end": "2024-03-01T10:30:00+01:00",
        "type": "feedback",
    }

    response = client.post(
        url_for("SensorAPI:post_annotation", id=sensor.id),
        json=annotation_data,
    )

    assert response.status_code == expected_status_code

    if expected_status_code == 201:
        # Verify response format
        assert "id" in response.json
        assert response.json["content"] == "Sensor calibration performed"
        assert response.json["type"] == "feedback"

        # Verify annotation is linked to sensor
        annotation = client.application.db.session.get(Annotation, response.json["id"])
        assert annotation in sensor.annotations


@pytest.mark.parametrize(
    "annotation_type",
    ["alert", "holiday", "label", "feedback", "warning", "error"],
)
def test_post_annotation_valid_types(client, setup_api_test_data, annotation_type):
    """Test that all valid annotation types are accepted.

    Validates the six allowed annotation types:
    - alert
    - holiday
    - label
    - feedback
    - warning
    - error
    """
    # Use an admin user for permissions
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": f"Test {annotation_type} annotation",
        "start": "2024-04-01T00:00:00+01:00",
        "end": "2024-04-01T01:00:00+01:00",
        "type": annotation_type,
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 201
    assert response.json["type"] == annotation_type


def test_post_annotation_invalid_type(client, setup_api_test_data):
    """Test that invalid annotation types are rejected with 422 Unprocessable Entity.

    The type field must be one of the six valid enum values.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Test annotation with invalid type",
        "start": "2024-05-01T00:00:00+01:00",
        "end": "2024-05-01T01:00:00+01:00",
        "type": "invalid_type",  # Not in the allowed enum
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "missing_field",
    ["content", "start", "end"],
)
def test_post_annotation_missing_required_fields(
    client, setup_api_test_data, missing_field
):
    """Test that missing required fields are rejected with 422.

    Required fields are:
    - content
    - start
    - end
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    # Create a complete annotation, then remove the field to test
    annotation_data = {
        "content": "Test annotation",
        "start": "2024-06-01T00:00:00+01:00",
        "end": "2024-06-01T01:00:00+01:00",
    }
    del annotation_data[missing_field]

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 422


def test_post_annotation_content_too_long(client, setup_api_test_data):
    """Test that content exceeding 1024 characters is rejected.

    The content field has a maximum length of 1024 characters.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    # Create content that exceeds 1024 characters
    long_content = "x" * 1025

    annotation_data = {
        "content": long_content,
        "start": "2024-07-01T00:00:00+01:00",
        "end": "2024-07-01T01:00:00+01:00",
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 422


def test_post_annotation_end_before_start(client, setup_api_test_data):
    """Test that end time before start time is rejected.

    The schema validates that end must be after start.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Invalid time range",
        "start": "2024-08-01T02:00:00+01:00",
        "end": "2024-08-01T01:00:00+01:00",  # Before start
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 422


def test_post_annotation_end_equal_to_start(client, setup_api_test_data):
    """Test that end time equal to start time is rejected.

    The schema validates that end must be after start (not equal).
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Zero duration annotation",
        "start": "2024-09-01T01:00:00+01:00",
        "end": "2024-09-01T01:00:00+01:00",  # Equal to start
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 422


def test_post_annotation_not_found(client, setup_api_test_data):
    """Test that posting to non-existent entity returns 422 Unprocessable Entity.

    Validates that:
    - Non-existent account ID returns 422
    - Non-existent asset ID returns 422
    - Non-existent sensor ID returns 422

    Note: The ID field validators return 422 (Unprocessable Entity) for invalid IDs,
    not 404 (Not Found), because they validate request data before reaching the endpoint.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    annotation_data = {
        "content": "Test annotation",
        "start": "2024-10-01T00:00:00+01:00",
        "end": "2024-10-01T01:00:00+01:00",
    }

    # Test with non-existent account
    response = client.post(
        url_for("AccountAPI:post_annotation", id=99999),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 422

    # Test with non-existent asset
    response = client.post(
        url_for("AssetAPI:post_annotation", id=99999),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 422

    # Test with non-existent sensor
    response = client.post(
        url_for("SensorAPI:post_annotation", id=99999),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 422


def test_post_annotation_idempotency(client, setup_api_test_data):
    """Test that posting the same annotation twice is idempotent.

    First POST should return 201 Created.
    Second POST with identical data should return 200 OK.
    Both should return the same annotation object.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Idempotent annotation",
        "start": "2024-11-01T00:00:00+01:00",
        "end": "2024-11-01T01:00:00+01:00",
        "type": "label",
    }

    # First POST - should create new annotation
    response1 = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response1.status_code == 201
    annotation_id_1 = response1.json["id"]

    # Count annotations before second POST
    annotation_count_before = client.application.db.session.scalar(
        select(func.count()).select_from(Annotation)
    )

    # Second POST - should return existing annotation
    response2 = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response2.status_code == 200
    annotation_id_2 = response2.json["id"]

    # Should be the same annotation
    assert annotation_id_1 == annotation_id_2

    # Count annotations after second POST
    annotation_count_after = client.application.db.session.scalar(
        select(func.count()).select_from(Annotation)
    )

    # No new annotation should have been created
    assert annotation_count_before == annotation_count_after


def test_post_annotation_with_prior(client, setup_api_test_data):
    """Test that prior can be optionally specified.

    When prior is provided, it should be stored and returned.
    When omitted, the API should use the current time (tested implicitly).
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    prior = "2024-12-01T12:00:00+01:00"

    annotation_data = {
        "content": "Annotation with belief time",
        "start": "2024-12-01T00:00:00+01:00",
        "end": "2024-12-01T01:00:00+01:00",
        "prior": prior,
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 201
    assert "prior" in response.json
    # Compare times after parsing to handle timezone conversions
    import dateutil.parser

    expected_time = dateutil.parser.isoparse(prior)
    actual_time = dateutil.parser.isoparse(response.json["prior"])
    assert expected_time == actual_time


def test_post_annotation_default_type(client, setup_api_test_data):
    """Test that type defaults to 'label' when not specified.

    The type field is optional and should default to 'label'.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Annotation with default type",
        "start": "2024-12-15T00:00:00+01:00",
        "end": "2024-12-15T01:00:00+01:00",
        # type is omitted
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 201
    assert response.json["type"] == "label"


def test_post_annotation_all_three_endpoints(client, setup_api_test_data):
    """Test that all three endpoints work correctly with the same annotation data.

    This comprehensive test validates that:
    - Account annotation endpoint works
    - Asset annotation endpoint works
    - Sensor annotation endpoint works

    All with the same user and similar data.
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")

    # Get test entities
    supplier_account = find_user_by_email("test_supplier_user_4@seita.nl").account
    asset = client.application.db.session.execute(
        select(GenericAsset).filter_by(name="incineration line")
    ).scalar_one()
    sensor = client.application.db.session.execute(
        select(Sensor).filter_by(name="some gas sensor")
    ).scalar_one()

    # Test account annotation
    response = client.post(
        url_for("AccountAPI:post_annotation", id=supplier_account.id),
        json={
            "content": "Account-level annotation",
            "start": "2025-01-01T00:00:00+01:00",
            "end": "2025-01-01T01:00:00+01:00",
        },
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 201
    account_annotation_id = response.json["id"]

    # Test asset annotation
    response = client.post(
        url_for("AssetAPI:post_annotation", id=asset.id),
        json={
            "content": "Asset-level annotation",
            "start": "2025-01-02T00:00:00+01:00",
            "end": "2025-01-02T01:00:00+01:00",
        },
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 201
    asset_annotation_id = response.json["id"]

    # Test sensor annotation
    response = client.post(
        url_for("SensorAPI:post_annotation", id=sensor.id),
        json={
            "content": "Sensor-level annotation",
            "start": "2025-01-03T00:00:00+01:00",
            "end": "2025-01-03T01:00:00+01:00",
        },
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 201
    sensor_annotation_id = response.json["id"]

    # Verify all annotations are distinct
    assert account_annotation_id != asset_annotation_id
    assert account_annotation_id != sensor_annotation_id
    assert asset_annotation_id != sensor_annotation_id

    # Verify annotations are correctly linked
    db = client.application.db
    account_annotation = db.session.get(Annotation, account_annotation_id)
    asset_annotation = db.session.get(Annotation, asset_annotation_id)
    sensor_annotation = db.session.get(Annotation, sensor_annotation_id)

    assert account_annotation in supplier_account.annotations
    assert asset_annotation in asset.annotations
    assert sensor_annotation in sensor.annotations


def test_post_annotation_response_schema(client, setup_api_test_data):
    """Test that the response schema includes all expected fields.

    The response should include:
    - id (integer)
    - content (string)
    - start (ISO 8601 datetime)
    - end (ISO 8601 datetime)
    - type (string)
    - prior (ISO 8601 datetime)
    - source_id (integer)
    """
    from flexmeasures.api.tests.utils import get_auth_token

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    account = client.application.db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()

    annotation_data = {
        "content": "Complete response test",
        "start": "2025-02-01T00:00:00+01:00",
        "end": "2025-02-01T01:00:00+01:00",
        "type": "warning",
    }

    response = client.post(
        url_for("AccountAPI:post_annotation", id=account.id),
        json=annotation_data,
        headers={"Authorization": auth_token},
    )

    assert response.status_code == 201

    # Check all expected fields are present
    assert "id" in response.json
    assert "content" in response.json
    assert "start" in response.json
    assert "end" in response.json
    assert "type" in response.json
    assert "prior" in response.json
    assert "source_id" in response.json

    # Verify field types and values
    assert isinstance(response.json["id"], int)
    assert response.json["content"] == "Complete response test"
    assert response.json["type"] == "warning"
    assert isinstance(response.json["source_id"], int)

    # Verify datetime fields are in ISO format
    assert "T" in response.json["start"]
    assert "T" in response.json["end"]
    # prior may be None if not explicitly set
    if response.json["prior"] is not None:
        assert "T" in response.json["prior"]
