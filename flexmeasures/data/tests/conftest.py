from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from random import random

import pandas as pd
import numpy as np
from flask_sqlalchemy import SQLAlchemy
from statsmodels.api import OLS
import timely_beliefs as tb
from sqlalchemy import select
from flexmeasures.data.models.reporting import Reporter

from flexmeasures.data.schemas.reporting import ReporterParametersSchema
from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief, Sensor
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
            datetime(2015, 1, 1), datetime(2015, 1, 2, 23, 45), freq="15T"
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
