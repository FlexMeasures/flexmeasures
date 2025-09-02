from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from random import random

import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy
from statsmodels.api import OLS
from flexmeasures import AssetType, Asset, Sensor
import timely_beliefs as tb
from sqlalchemy import select
from flexmeasures.data.models.reporting import Reporter

from flexmeasures.data.schemas.reporting import ReporterParametersSchema
from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.forecasting import model_map
from flexmeasures.data.models.forecasting.model_spec_factory import (
    create_initial_model_specs,
)
from flexmeasures.utils.time_utils import as_server_time

from marshmallow import fields
from marshmallow import Schema


@pytest.fixture(scope="module")
def setup_test_data(
    db,
    app,
    add_market_prices,
    setup_assets,
    setup_generic_asset_types,
):
    """
    Adding a few forecasting jobs (based on data made in flexmeasures.conftest).
    """
    print("Setting up data for data tests on %s" % db.engine)

    add_test_weather_sensor_and_forecasts(db, setup_generic_asset_types)

    print("Done setting up data for data tests")
    return setup_assets


@pytest.fixture(scope="function")
def setup_fresh_test_data(
    fresh_db,
    setup_markets_fresh_db,
    setup_accounts_fresh_db,
    setup_assets_fresh_db,
    setup_generic_asset_types_fresh_db,
    app,
) -> dict[str, GenericAsset]:
    add_test_weather_sensor_and_forecasts(fresh_db, setup_generic_asset_types_fresh_db)
    return setup_assets_fresh_db


def add_test_weather_sensor_and_forecasts(db: SQLAlchemy, setup_generic_asset_types):
    """one day of test data (one complete sine curve) for two sensors"""
    data_source = db.session.execute(
        select(DataSource).filter_by(name="Seita", type="demo script")
    ).scalar_one_or_none()
    weather_station = GenericAsset(
        name="Test weather station farther away",
        generic_asset_type=setup_generic_asset_types["weather_station"],
        latitude=100,
        longitude=100,
    )
    for sensor_name, unit in (("irradiance", "kW/m²"), ("wind speed", "m/s")):
        sensor = Sensor(name=sensor_name, generic_asset=weather_station, unit=unit)
        db.session.add(sensor)
        time_slots = pd.date_range(
            datetime(2015, 1, 1), datetime(2015, 1, 2, 23, 45), freq="15min"
        )
        values = [random() * (1 + np.sin(x / 15)) for x in range(len(time_slots))]
        if sensor_name == "temperature":
            values = [value * 17 for value in values]
        if sensor_name == "wind speed":
            values = [value * 45 for value in values]
        if sensor_name == "irradiance":
            values = [value * 600 for value in values]
        for dt, val in zip(time_slots, values):
            db.session.add(
                TimedBelief(
                    sensor=sensor,
                    event_start=as_server_time(dt),
                    event_value=val,
                    belief_horizon=timedelta(hours=6),
                    source=data_source,
                )
            )


@pytest.fixture(scope="module", autouse=True)
def add_failing_test_model(db):
    """Add a test model specs to the lookup which should fail due to missing data.
    It falls back to linear OLS (which falls back to naive)."""

    def test_specs(**args):
        """Customize initial specs with OLS and too early training start."""
        model_specs = create_initial_model_specs(**args)
        model_specs.set_model(OLS)
        model_specs.start_of_training = model_specs.start_of_training - timedelta(
            days=365
        )
        model_identifier = "failing-test model v1"
        return model_specs, model_identifier, "linear-OLS"

    model_map["failing-test"] = test_specs


@pytest.fixture(scope="module")
def add_nearby_weather_sensors(db, add_weather_sensors) -> dict[str, Sensor]:
    temp_sensor_location = add_weather_sensors["temperature"].generic_asset.location
    weather_station_type = db.session.execute(
        select(GenericAssetType).filter_by(name="weather station")
    ).scalar_one_or_none()
    farther_weather_station = GenericAsset(
        name="Test weather station farther away",
        generic_asset_type=weather_station_type,
        latitude=temp_sensor_location[0],
        longitude=temp_sensor_location[1] + 0.1,
    )
    db.session.add(farther_weather_station)
    farther_temp_sensor = Sensor(
        name="temperature",
        generic_asset=farther_weather_station,
        event_resolution=timedelta(minutes=5),
        unit="°C",
    )
    db.session.add(farther_temp_sensor)
    even_farther_weather_station = GenericAsset(
        name="Test weather station even farther away",
        generic_asset_type=weather_station_type,
        latitude=temp_sensor_location[0],
        longitude=temp_sensor_location[1] + 0.2,
    )
    db.session.add(even_farther_weather_station)
    even_farther_temp_sensor = Sensor(
        name="temperature",
        generic_asset=even_farther_weather_station,
        event_resolution=timedelta(minutes=5),
        unit="°C",
    )
    db.session.add(even_farther_temp_sensor)
    add_weather_sensors["farther_temperature"] = farther_temp_sensor
    add_weather_sensors["even_farther_temperature"] = even_farther_temp_sensor
    return add_weather_sensors


@pytest.fixture(scope="module")
def setup_annotations(
    db,
    battery_soc_sensor,
    setup_sources,
    app,
):
    """Set up an annotation for an account, an asset and a sensor."""
    sensor = battery_soc_sensor
    asset = sensor.generic_asset
    account = asset.owner
    source = setup_sources["Seita"]
    annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    account.annotations.append(annotation)
    asset.annotations.append(annotation)
    sensor.annotations.append(annotation)
    db.session.flush()
    return dict(
        annotation=annotation,
        account=account,
        asset=asset,
        sensor=sensor,
    )


@pytest.fixture(scope="module")
def test_reporter(app, db, add_nearby_weather_sensors):
    class TestReporterConfigSchema(Schema):
        a = fields.Str()

    class TestReporterParametersSchema(ReporterParametersSchema):
        b = fields.Str(required=False)

    class TestReporter(Reporter):
        _config_schema = TestReporterConfigSchema()
        _parameters_schema = TestReporterParametersSchema()

        def _compute_report(self, **kwargs) -> list:
            start = kwargs.get("start")
            end = kwargs.get("end")
            sensor = kwargs["output"][0]["sensor"]
            resolution = sensor.event_resolution

            index = pd.date_range(start=start, end=end, freq=resolution)

            r = pd.DataFrame()
            r["event_start"] = index
            r["belief_time"] = index
            r["source"] = self.data_source
            r["cumulative_probability"] = 0.5
            r["event_value"] = 0

            bdf = tb.BeliefsDataFrame(r, sensor=sensor)

            return [{"data": bdf, "sensor": sensor}]

    app.data_generators["reporter"].update({"TestReporter": TestReporter})

    config = dict(a="b")

    ds = TestReporter(config=config).data_source

    assert ds.name == app.config.get("FLEXMEASURES_DEFAULT_DATASOURCE")

    db.session.add(ds)
    db.session.commit()

    return ds


@pytest.fixture(scope="function")
def smart_building_types(app, fresh_db, setup_generic_asset_types_fresh_db):
    site = AssetType(name="site")
    building = AssetType(name="building")
    ev = AssetType(name="ev")
    heat_buffer = AssetType(name="heat buffer")

    fresh_db.session.add_all([site, building, ev, heat_buffer])
    fresh_db.session.flush()

    return (
        site,
        setup_generic_asset_types_fresh_db["solar"],
        building,
        setup_generic_asset_types_fresh_db["battery"],
        ev,
        heat_buffer,
    )


@pytest.fixture(scope="function")
def smart_building(app, fresh_db, smart_building_types):
    """
    Topology of the sytstem:

                           +---------+
                           |         |
         +------------------  Site   +--------------+------------------+
         |                 |         |              |                  |
         |                 +-+----+--+              |                  |
         |                   |    |                 |                  |
         |                   |    |                 |                  |
         |              +----+    +--+              |                  |
         |              |            |              |                  |
    +----+----+  +------+-----+   +--+---+   +------+------+    +------+------+
    |         |  |            |   |      |   |             |    |             |
    |  Solar  |  |  Building  |   |  EV  |   |   Battery   |    | Heat Buffer |
    |         |  |            |   |      |   |             |    |             |
    +---------+  +------------+   +------+   +-------------+    +-------------+

    Diagram created with: https://textik.com/#924f8a2112551f92

    """
    site, solar, building, battery, ev, heat_buffer = smart_building_types
    coordinates = {"latitude": 0, "longitude": 0}

    test_site = Asset(name="Test Site", generic_asset_type_id=site.id, **coordinates)
    fresh_db.session.add(test_site)
    fresh_db.session.flush()

    test_building = Asset(
        name="Test Building",
        generic_asset_type_id=building.id,
        parent_asset_id=test_site.id,
        **coordinates,
    )
    test_solar = Asset(
        name="Test Solar",
        generic_asset_type_id=solar.id,
        parent_asset_id=test_site.id,
        **coordinates,
    )
    test_battery = Asset(
        name="Test Battery",
        generic_asset_type_id=battery.id,
        parent_asset_id=test_site.id,
        **coordinates,
    )
    test_ev = Asset(
        name="Test EV",
        generic_asset_type_id=ev.id,
        parent_asset_id=test_site.id,
        **coordinates,
    )
    test_battery_1h = Asset(
        name="Test Battery 1h",
        generic_asset_type_id=battery.id,
        parent_asset_id=test_site.id,
        **coordinates,
    )

    test_heat_buffer = Asset(
        name="Test Heat Buffer",
        generic_asset_type_id=heat_buffer.id,
        parent_asset_id=test_site.id,
        **coordinates,
    )

    assets = (
        test_site,
        test_building,
        test_solar,
        test_battery,
        test_ev,
        test_battery_1h,
        test_heat_buffer,
    )

    fresh_db.session.add_all(assets)
    fresh_db.session.flush()

    power_sensors = []
    soc_sensors = []

    for asset in assets:
        # Add power sensor
        sensor = Sensor(
            name="power",
            unit="MW",
            event_resolution=(
                timedelta(hours=1)
                if asset.name == "Test Battery 1h"
                else timedelta(minutes=15)
            ),
            generic_asset=asset,
            timezone="Europe/Amsterdam",
        )
        power_sensors.append(sensor)

        # Add SOC sensors
        sensor = Sensor(
            "state of charge",
            unit="MWh",
            event_resolution=timedelta(hours=0),
            generic_asset=asset,
            timezone="Europe/Amsterdam",
        )
        soc_sensors.append(sensor)

    fresh_db.session.add_all(power_sensors)
    fresh_db.session.add_all(soc_sensors)
    fresh_db.session.flush()
    asset_names = [asset.name for asset in assets]
    return (
        dict(zip(asset_names, assets)),
        dict(zip(asset_names, power_sensors)),
        dict(zip(asset_names, soc_sensors)),
    )


@pytest.fixture(scope="function")
def flex_description_sequential(
    smart_building, setup_markets_fresh_db, add_market_prices_fresh_db
):
    """Set up a flex-context and a partially deserialized flex-model.

    Specifically, the main flex model is deserialized, while the sensors' individual flex models are still serialized.
    """
    assets, sensors, soc_sensors = smart_building

    flex_model = [
        {
            "sensor": sensors["Test EV"],
            "sensor_flex_model": {
                "consumption-capacity": "5kW",
                "production-capacity": "0kW",
                "power-capacity": "5kW",
                "soc-at-start": 0.00,  # 0 kWh
                "soc-unit": "MWh",
                "soc-min": 0.0,
                "soc-max": 0.05,  # 50 kWh
                "soc-targets": [
                    {
                        "start": "2015-01-03T00:00:00+01:00",
                        "end": "2015-01-03T05:00:00+01:00",
                        "value": 0.0,
                    },
                    {
                        "datetime": "2015-01-03T07:45:00+01:00",
                        "value": 0.0125,
                    },  # 12.5 kWh
                    {"datetime": "2015-01-03T17:45:00+01:00", "value": 0.025},  # 25 kWh
                    {
                        "datetime": "2015-01-03T23:45:00+01:00",
                        "value": 0.0375,
                    },  # 37.5 kWh
                ],
            },
        },
        {
            "sensor": sensors["Test Battery"],
            "sensor_flex_model": {
                "consumption-capacity": "0kW",
                "production-capacity": "5kW",
                "power-capacity": "5kW",
                "soc-at-start": 0.1,  # 100 kWh
                "soc-unit": "MWh",
                "soc-min": 0.0,
                "soc-max": 0.1,  # 100 kWh
                "soc-targets": [
                    {
                        "datetime": "2015-01-03T03:00:00+01:00",
                        "value": 0.094,
                    }  # 6 kWh discharge
                ],
            },
        },
    ]
    flex_context = {
        "consumption-price-sensor": setup_markets_fresh_db["epex_da"].id,
        "production-price-sensor": setup_markets_fresh_db["epex_da"].id,
        "inflexible-device-sensors": [
            sensors["Test Solar"].id,
            sensors["Test Building"].id,
        ],
        "site-production-capacity": "2kW",
        "site-consumption-capacity": "5kW",
    }
    return dict(flex_model=flex_model, flex_context=flex_context)
