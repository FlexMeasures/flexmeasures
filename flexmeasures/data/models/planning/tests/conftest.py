from __future__ import annotations

from datetime import timedelta
import pytest

from timely_beliefs.sensors.func_store.knowledge_horizons import at_date
import pandas as pd

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import Sensor, TimedBelief


@pytest.fixture(params=["appsi_highs", "cbc"])
def app_with_each_solver(app, request):
    """Set up the app config to run with different solvers.

    A test that uses this fixtures runs all of its test cases with HiGHS and then again with Cbc.
    """
    original_solver = app.config["FLEXMEASURES_LP_SOLVER"]
    app.config["FLEXMEASURES_LP_SOLVER"] = request.param

    yield app

    # Restore original config setting for the solver
    app.config["FLEXMEASURES_LP_SOLVER"] = original_solver


@pytest.fixture(scope="module", autouse=True)
def setup_planning_test_data(db, add_market_prices, add_charging_station_assets):
    """
    Set up data for all planning tests.
    """
    print("Setting up data for planning tests on %s" % db.engine)
    return add_charging_station_assets


@pytest.fixture(scope="module")
def create_test_tariffs(db, setup_accounts, setup_sources) -> dict[str, Sensor]:
    """Create a fixed consumption tariff and a fixed feed-in tariff that is lower."""

    market_type = GenericAssetType(
        name="tariff market",
    )
    db.session.add(market_type)
    contract = GenericAsset(
        name="supply contract",
        generic_asset_type=market_type,
        owner=setup_accounts["Supplier"],
    )
    db.session.add(contract)
    consumption_price_sensor = Sensor(
        name="fixed consumption tariff",
        generic_asset=contract,
        event_resolution=timedelta(hours=24 * 365),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(consumption_price_sensor)
    production_price_sensor = Sensor(
        name="fixed feed-in tariff",
        generic_asset=contract,
        event_resolution=timedelta(hours=24 * 365),
        unit="EUR/MWh",
        knowledge_horizon=(at_date, {"knowledge_time": "2014-11-01T00:00+01:00"}),
    )
    db.session.add(production_price_sensor)

    # Add prices
    consumption_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=300 * 1.21,
        source=setup_sources["Seita"],
        sensor=consumption_price_sensor,
    )
    db.session.add(consumption_price)
    production_price = TimedBelief(
        event_start="2015-01-01T00:00+01:00",
        belief_time="2014-11-01T00:00+01:00",  # publication date
        event_value=300,
        source=setup_sources["Seita"],
        sensor=production_price_sensor,
    )
    db.session.add(production_price)
    db.session.flush()  # make sure that prices are assigned to price sensors
    return {
        "consumption_price_sensor": consumption_price_sensor,
        "production_price_sensor": production_price_sensor,
    }


@pytest.fixture(scope="module")
def building(db, setup_accounts, setup_markets) -> GenericAsset:
    """
    Set up a building.
    """
    building_type = GenericAssetType(name="building")
    db.session.add(building_type)
    building = GenericAsset(
        name="building",
        generic_asset_type=building_type,
        owner=setup_accounts["Prosumer"],
        attributes=dict(
            market_id=setup_markets["epex_da"].id,
            capacity_in_mw=2,
        ),
    )
    db.session.add(building)
    return building


@pytest.fixture(scope="module")
def flexible_devices(db, building) -> dict[str, Sensor]:
    """
    Set up power sensors for flexible devices:
    - A battery
    - A Charge Point (todo)
    """
    battery_sensor = Sensor(
        name="battery power sensor",
        generic_asset=building,
        event_resolution=timedelta(minutes=15),
        attributes=dict(
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
        ),
        unit="MW",
    )
    db.session.add(battery_sensor)
    return {
        battery_sensor.name: battery_sensor,
    }


@pytest.fixture(scope="module")
def inflexible_devices(db, building) -> dict[str, Sensor]:
    """
    Set up power sensors for inflexible devices:
    - A PV panel
    - Residual building demand
    """
    pv_sensor = Sensor(
        name="PV power sensor",
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit="kW",
        attributes={"capacity_in_mw": 2},
    )
    db.session.add(pv_sensor)
    residual_demand_sensor = Sensor(
        name="residual demand power sensor",
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit="kW",
        attributes={"capacity_in_mw": 2},
    )
    db.session.add(residual_demand_sensor)
    return {
        pv_sensor.name: pv_sensor,
        residual_demand_sensor.name: residual_demand_sensor,
    }


@pytest.fixture(scope="module")
def add_inflexible_device_forecasts(
    db, inflexible_devices, setup_sources
) -> dict[Sensor, list[int | float]]:
    """
    Set up inflexible devices and forecasts.
    """
    # 2 days of test data
    time_slots = initialize_index(
        start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam"),
        resolution="15T",
    )

    # PV (8 hours at zero capacity, 8 hours at 90% capacity, and again 8 hours at zero capacity)
    headroom = 0.1  # 90% of nominal capacity
    pv_sensor = inflexible_devices["PV power sensor"]
    capacity = pv_sensor.get_attribute("capacity_in_mw")
    pv_values = (
        [0] * (8 * 4) + [(1 - headroom) * capacity] * (8 * 4) + [0] * (8 * 4)
    ) * (len(time_slots) // (24 * 4))
    add_as_beliefs(db, pv_sensor, pv_values, time_slots, setup_sources["Seita"])

    # Residual demand (1 MW continuously)
    residual_demand_sensor = inflexible_devices["residual demand power sensor"]
    residual_demand_values = [-1] * len(time_slots)
    add_as_beliefs(
        db,
        residual_demand_sensor,
        residual_demand_values,
        time_slots,
        setup_sources["Seita"],
    )

    return {
        pv_sensor: pv_values,
        residual_demand_sensor: residual_demand_values,
    }


@pytest.fixture(scope="module")
def process(db, building, setup_sources) -> dict[str, Sensor]:
    """
    Set up a process sensor where the output of the optimization is stored.
    """
    _process = Sensor(
        name="Process",
        generic_asset=building,
        event_resolution=timedelta(hours=1),
        unit="kWh",
    )
    db.session.add(_process)

    return _process


@pytest.fixture(scope="module")
def efficiency_sensors(db, add_battery_assets, setup_sources) -> dict[str, Sensor]:
    battery = add_battery_assets["Test battery"]
    sensors = {}
    sensor_specs = [("efficiency", timedelta(minutes=15), 90)]

    for name, resolution, value in sensor_specs:
        # 1 days of test data
        time_slots = initialize_index(
            start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
            end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
            resolution=resolution,
        )

        efficiency_sensor = Sensor(
            name=name,
            unit="%",
            event_resolution=resolution,
            generic_asset=battery,
        )
        db.session.add(efficiency_sensor)
        db.session.flush()

        steps_in_hour = int(timedelta(hours=1) / resolution)
        efficiency = [value] * len(time_slots)

        add_as_beliefs(
            db,
            efficiency_sensor,
            efficiency[:-steps_in_hour],
            time_slots[:-steps_in_hour],
            setup_sources["Seita"],
        )
        sensors[name] = efficiency_sensor

    return sensors


@pytest.fixture(scope="module")
def add_stock_delta(db, add_battery_assets, setup_sources) -> dict[str, Sensor]:
    """
    Different usage forecast sensors are defined:
        - "delta fails": the usage forecast exceeds the maximum power.
        - "delta": the usage forecast can be fulfilled just right. This coincides with the schedule resolution.
        - "delta hourly": the event resolution is changed to test that the schedule is still feasible.
                          This has a greater resolution.
        - "delta 5min": the event resolution is reduced even more. This sensor has a resolution smaller than that used
                        for the scheduler.
    """

    battery = add_battery_assets["Test battery"]
    capacity = battery.get_attribute("capacity_in_mw")
    sensors = {}
    sensor_specs = [
        ("delta fails", timedelta(minutes=15), capacity * 1.2),
        ("delta", timedelta(minutes=15), capacity),
        ("delta hourly", timedelta(hours=1), capacity),
        ("delta 5min", timedelta(minutes=5), capacity),
    ]

    for name, resolution, value in sensor_specs:
        # 1 days of test data
        time_slots = initialize_index(
            start=pd.Timestamp("2015-01-01").tz_localize("Europe/Amsterdam"),
            end=pd.Timestamp("2015-01-02").tz_localize("Europe/Amsterdam"),
            resolution=resolution,
        )

        stock_delta_sensor = Sensor(
            name=name,
            unit="MW",
            event_resolution=resolution,
            generic_asset=battery,
        )
        db.session.add(stock_delta_sensor)
        db.session.flush()

        stock_gain = [value] * len(time_slots)

        add_as_beliefs(
            db,
            stock_delta_sensor,
            stock_gain,
            time_slots,
            setup_sources["Seita"],
        )
        sensors[name] = stock_delta_sensor

    return sensors


def add_as_beliefs(db, sensor, values, time_slots, source):
    beliefs = [
        TimedBelief(
            event_start=dt,
            belief_time=time_slots[0],
            event_value=val,
            source=source,
            sensor=sensor,
        )
        for dt, val in zip(time_slots, values)
    ]
    db.session.add_all(beliefs)
