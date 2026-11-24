"""A host's generator behind an automation on a public asset is readable by all, but not theirs to use."""

import pytest
from flask import url_for

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.services.data_sources import (
    user_may_read_source,
    user_may_use_source,
)


@pytest.fixture
def public_automation_source(db):
    asset = GenericAsset(
        name="public weather station (automation test)",
        generic_asset_type=GenericAssetType(name="public automation test type"),
    )
    generator = DataSource(
        name="host weather forecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {"model": "HostSecretModel"}}},
    )
    automation = Automation(
        asset=asset,
        generator=generator,
        type="forecasting",
        name="public weather forecasts",
        cronstr="0 6 * * *",
        parameters={},
    )
    db.session.add_all([asset, generator, automation])
    db.session.flush()
    return generator


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_public_automation_source_is_readable_but_not_usable(
    client, setup_api_test_data, requesting_user, public_automation_source
):
    assert user_may_read_source(public_automation_source)
    assert not user_may_use_source(public_automation_source)

    response = client.get(url_for("SourceAPI:get", id=public_automation_source.id))
    assert response.status_code == 200
    assert response.json["name"] == "host weather forecaster"
    assert "HostSecretModel" not in str(response.json)
