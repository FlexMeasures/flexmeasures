import json

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.api.tests.utils import AccountContext
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data, check_audit_log_event


@pytest.mark.parametrize(
    "requesting_user",
    [
        "test_admin_user@seita.nl",  # has the "site-admin" role
        "test_prosumer_user_2@seita.nl",  # has the "account-admin" role
    ],
    indirect=True,
)
def test_post_an_asset_as_admin(client, setup_api_fresh_test_data, requesting_user, db):
    """
    Post one extra asset, as an admin user.
    """
    with AccountContext("Test Prosumer Account") as prosumer:
        post_data = get_asset_post_data(
            account_id=prosumer.id,
            asset_type_id=prosumer.generic_assets[0].generic_asset_type.id,
        )
    if requesting_user.email == "test_prosumer_user_2@seita.nl":
        post_data["name"] = "Test battery 3"
    post_assets_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: GenericAsset = db.session.execute(
        select(GenericAsset).filter_by(name=post_data["name"])
    ).scalar_one_or_none()
    assert asset is not None
    assert asset.latitude == 30.1


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_edit_an_asset(client, setup_api_fresh_test_data, requesting_user, db):
    with AccountContext("Test Supplier Account") as supplier:
        existing_asset = supplier.generic_assets[0]

    post_data = dict(latitude=10)
    edit_asset_response = client.patch(
        url_for("AssetAPI:patch", id=existing_asset.id),
        json=post_data,
    )
    assert edit_asset_response.status_code == 200
    updated_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset.id)
    ).scalar_one_or_none()
    assert updated_asset.latitude == 10  # changed value
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.name == existing_asset.name


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_an_asset(client, setup_api_fresh_test_data, requesting_user, db):
    with AccountContext("Test Prosumer Account") as prosumer:
        existing_asset_id = prosumer.generic_assets[0].id

    delete_asset_response = client.delete(
        url_for("AssetAPI:delete", id=existing_asset_id),
    )
    assert delete_asset_response.status_code == 204
    deleted_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset_id)
    ).scalar_one_or_none()
    assert deleted_asset is None


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_patch_asset_accepts_flex_context_object(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    db = fresh_db
    with AccountContext("Test Supplier Account") as supplier:
        existing_asset = supplier.generic_assets[0]
    assert existing_asset.flex_context == {}

    patch_data = {
        "flex_context": {
            "site-power-capacity": "1000 kW",
        }
    }
    response = client.patch(
        url_for("AssetAPI:patch", id=existing_asset.id),
        json=patch_data,
    )

    assert response.status_code == 200
    updated_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset.id)
    ).scalar_one_or_none()
    assert updated_asset is not None
    assert updated_asset.flex_context["site-power-capacity"] == "1000 kW"


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_asset_cleans_stale_asset_references_in_sensors_to_show(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """Verify that deleting an asset cleans up stale asset references in other assets' sensors_to_show."""
    db = fresh_db
    deleted_asset = setup_api_fresh_test_data["some gas sensor"].generic_asset
    deleted_asset_id = deleted_asset.id
    deleted_asset_name = deleted_asset.name
    referenced_sensor = setup_api_fresh_test_data["some temperature sensor"]

    # Use a dedicated asset as the reference holder so deleting `deleted_asset`
    # does not remove the object we assert on later.
    referencing_asset = GenericAsset(
        name="stale-asset-ref-holder",
        generic_asset_type_id=deleted_asset.generic_asset_type_id,
        account_id=requesting_user.account_id,
    )
    db.session.add(referencing_asset)
    db.session.flush()

    referencing_asset.sensors_to_show = [
        {
            "title": "Mixed graph",
            "plots": [
                {"sensor": referenced_sensor.id},
                {"asset": deleted_asset_id, "flex-model": "soc-min"},
            ],
        }
    ]
    db.session.add(referencing_asset)
    db.session.commit()

    delete_asset_response = client.delete(
        url_for("AssetAPI:delete", id=deleted_asset_id),
    )
    assert delete_asset_response.status_code == 204

    updated_referencing_asset = db.session.get(GenericAsset, referencing_asset.id)
    assert updated_referencing_asset is not None
    assert str(deleted_asset_id) not in json.dumps(
        updated_referencing_asset.sensors_to_show
    )

    check_audit_log_event(
        db=db,
        event=f"Removed asset reference '{deleted_asset_name}': {deleted_asset_id} from sensors-to-show (because asset has been deleted).",
        user=requesting_user,
        asset=updated_referencing_asset,
    )
