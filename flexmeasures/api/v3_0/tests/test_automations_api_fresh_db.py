"""Permission regressions for automation API details."""

from datetime import timedelta

import pytest
from flask import url_for

from flexmeasures.data.models.automations import Automation
from flexmeasures import Forecaster
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.data_sources import get_data_generator


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_details_reject_inaccessible_sensor_metadata(
    client,
    fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    requesting_user,
):
    prosumer_asset = setup_generic_assets_fresh_db["test_battery"]
    supplier_asset = setup_generic_assets_fresh_db["test_wind_turbine"]
    output_sensor = Sensor(
        name="prosumer output",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=prosumer_asset,
    )
    hidden_sensor = Sensor(
        name="private supplier regressor",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=supplier_asset,
    )
    fresh_db.session.add_all([output_sensor, hidden_sensor])
    fresh_db.session.flush()
    forecaster = get_data_generator(
        source=None,
        model="TrainPredictPipeline",
        config={"regressors": [hidden_sensor.id]},
        save_config=True,
        data_generator_type=Forecaster,
    )
    assert forecaster is not None
    generator = forecaster.data_source
    automation = Automation(
        asset=prosumer_asset,
        generator=generator,
        type="forecasts",
        name="Cross-organisation details",
        cronstr="0 6 * * *",
        parameters={"sensor": output_sensor.id},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    response = client.get(
        url_for(
            "AssetAPI:get_automation",
            id=prosumer_asset.id,
            automation_id=automation.id,
        )
    )

    assert response.status_code == 403
    assert hidden_sensor.name not in response.text
