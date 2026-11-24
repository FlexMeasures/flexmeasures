"""One automation whose sensors cannot be resolved does not break the lookup of the automations using a sensor."""

import logging

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services import automations as automation_services


def test_broken_automation_does_not_break_the_lookup(app, db, monkeypatch, caplog):
    asset_type = GenericAssetType(name="involved-sensor test asset type")
    asset = GenericAsset(
        name="involved-sensor test asset", generic_asset_type=asset_type
    )
    sensor = Sensor(name="involved sensor", generic_asset=asset, unit="kW")
    generator = DataSource(
        name="involved-sensor test generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    broken, working = (
        Automation(
            asset=asset,
            generator=generator,
            type="forecasting",
            name=name,
            cronstr="0 6 * * *",
            parameters={},
        )
        for name in ("broken automation", "working automation")
    )
    db.session.add_all([asset, sensor, generator, broken, working])
    db.session.flush()

    def resolve(automation):
        if automation.id == broken.id:
            # e.g. a custom-scheduler attribute naming a module which is not there
            raise ModuleNotFoundError("No module named 'gone'")
        if automation.id == working.id:
            return {"input_sensors": [sensor], "output_sensors": []}
        return {"input_sensors": [], "output_sensors": []}

    monkeypatch.setattr(automation_services, "resolve_automation_sensors", resolve)
    caplog.set_level(logging.WARNING)

    involved = automation_services.get_automations_involving_sensor(sensor)

    assert involved == [working]
    assert f"automation {broken.id}" in caplog.text
