from __future__ import annotations

from datetime import timezone

import pytest
from sqlalchemy.exc import IntegrityError

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


@pytest.fixture()
def automation_with_generator(fresh_db):
    asset_type = GenericAssetType(name="automation test asset type")
    asset = GenericAsset(name="automation test asset", generic_asset_type=asset_type)
    generator = DataSource(
        name="automation test generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    automation = Automation(
        asset=asset,
        generator=generator,
        type="forecasts",
        name="automation generator lifecycle test",
        cronstr="0 6 * * *",
        parameters={},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()
    return automation, generator


def test_referenced_automation_generator_cannot_be_deleted(
    fresh_db, automation_with_generator
):
    automation, generator = automation_with_generator
    automation_id = automation.id
    generator_id = generator.id

    fresh_db.session.delete(generator)
    with pytest.raises(IntegrityError):
        fresh_db.session.commit()
    fresh_db.session.rollback()

    persisted_automation = fresh_db.session.get(Automation, automation_id)
    assert persisted_automation is not None
    assert persisted_automation.generator_id == generator_id
    assert fresh_db.session.get(DataSource, generator_id) is not None

    fresh_db.session.delete(persisted_automation)
    fresh_db.session.commit()
    persisted_generator = fresh_db.session.get(DataSource, generator_id)
    fresh_db.session.delete(persisted_generator)
    fresh_db.session.commit()
    assert fresh_db.session.get(DataSource, generator_id) is None


def test_automation_requires_generator(fresh_db, automation_with_generator):
    automation, _ = automation_with_generator
    automation.generator = None

    with pytest.raises(IntegrityError):
        fresh_db.session.commit()


def test_automation_has_valid_timezone_and_aware_cursor(automation_with_generator):
    automation, _ = automation_with_generator

    assert automation.timezone == "Asia/Seoul"
    assert automation.cursor.tzinfo is not None
    assert automation.cursor.utcoffset() == timezone.utc.utcoffset(None)


def test_automation_rejects_invalid_timezone(automation_with_generator):
    automation, _ = automation_with_generator

    with pytest.raises(ValueError, match="does not exist"):
        automation.timezone = "Europe/NotAmsterdam"
