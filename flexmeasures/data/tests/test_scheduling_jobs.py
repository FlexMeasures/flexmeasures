from datetime import datetime, timedelta
import os
import inspect

import numpy as np
import pandas as pd
import pytz
import pytest
from rq.job import Job
from sqlalchemy import select

from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException
from flexmeasures.data.models.planning.utils import initialize_series
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.tests.utils import work_on_rq, exception_reporter
from flexmeasures.data.services.scheduling import (
    create_scheduling_job,
    load_custom_scheduler,
    handle_scheduling_exception,
)
from flexmeasures.utils.unit_utils import ur
from flexmeasures.utils.calculations import integrate_time_series


def test_scheduling_a_battery(
    fresh_db,
    app,
    add_battery_assets_fresh_db,
    setup_fresh_test_data,
    add_market_prices_fresh_db,
):
    """Test one clean run of one scheduling job:
    - data source was made,
    - schedule has been made
    """

    battery = add_battery_assets_fresh_db["Test battery"].sensors[0]
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)

    assert (
        fresh_db.session.execute(
            select(DataSource).filter_by(name="FlexMeasures", type="scheduler")
        ).scalar_one_or_none()
        is None
    )  # Make sure the scheduler data source isn't there

    job = create_scheduling_job(
        asset_or_sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        flex_model={
            "roundtrip-efficiency": "98%",
            "storage-efficiency": 0.999,
        },
    )

    print("Job: %s" % job.id)

    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    scheduler_source = fresh_db.session.execute(
        select(DataSource).filter_by(name="Seita", type="scheduler")
    ).scalar_one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there

    power_values = fresh_db.session.scalars(
        select(TimedBelief)
        .filter(TimedBelief.sensor_id == battery.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
    ).all()
    print([v.event_value for v in power_values])
    assert len(power_values) == 96
    assert (
        sum(v.event_value for v in power_values) < -0.5
    ), "some cycling should have occurred to make a profit, resulting in overall consumption due to losses"


scheduler_specs = {
    "module": None,  # use make_module_descr, see below
    "class": "DummyScheduler",
}


def make_module_descr(is_path):
    if is_path:
        path_to_here = os.path.dirname(__file__)
        return os.path.join(path_to_here, "dummy_scheduler.py")
    else:
        return "flexmeasures.data.tests.dummy_scheduler"


@pytest.mark.parametrize("is_path", [False, True])
def test_loading_custom_scheduler(is_path: bool):
    """
    Simply check if loading a custom scheduler works.
    """
    scheduler_specs["module"] = make_module_descr(is_path)
    custom_scheduler = load_custom_scheduler(scheduler_specs)
    assert custom_scheduler.__name__ == "DummyScheduler"
    assert "Just a dummy scheduler" in custom_scheduler.compute.__doc__

    data_source_info = custom_scheduler.get_data_source_info()
    assert data_source_info["name"] == "Test Organization"
    assert data_source_info["version"] == "3"
    assert data_source_info["model"] == "DummyScheduler"


@pytest.mark.parametrize("is_path", [False, True])
def test_assigning_custom_scheduler(
    fresh_db, app, add_battery_assets_fresh_db, is_path: bool
):
    """
    Test if the custom scheduler is picked up when we assign it to a Sensor,
    and that its dummy values are saved.
    """
    scheduler_specs["module"] = make_module_descr(is_path)

    battery = add_battery_assets_fresh_db["Test battery"].sensors[0]
    battery.attributes["custom-scheduler"] = scheduler_specs

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)

    job = create_scheduling_job(
        asset_or_sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
    )
    print("Job: %s" % job.id)

    work_on_rq(app.queues["scheduling"], exc_handler=exception_reporter)

    # make sure we saved the data source for later lookup
    redis_connection = app.queues["scheduling"].connection
    finished_job = Job.fetch(job.id, connection=redis_connection)
    assert finished_job.meta["data_source_info"]["model"] == scheduler_specs["class"]

    scheduler_source = fresh_db.session.execute(
        select(DataSource).filter_by(
            type="scheduler",
            **finished_job.meta["data_source_info"],
        )
    ).scalar_one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there

    power_values = fresh_db.session.scalars(
        select(TimedBelief)
        .filter(TimedBelief.sensor_id == battery.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
    ).all()
    assert len(power_values) == 96
    # test for negative value as we schedule consumption
    capacity = battery.get_attribute(
        "capacity_in_mw",
        ur.Quantity(battery.get_attribute("site-power-capacity")).to("MW").magnitude,
    )
    assert all([v.event_value == -1 * capacity for v in power_values])


def create_test_scheduler(name, compute_fails=False, fallback_class=None):
    def compute(self):
        """
        This function can be set to fail by using compute_fails=True
        """

        if compute_fails:
            raise InfeasibleProblemException()

        capacity = self.sensor.get_attribute(
            "capacity_in_mw",
            ur.Quantity(self.sensor.get_attribute("site-power-capacity"))
            .to("MW")
            .magnitude,
        )
        return initialize_series(  # simply creates a Pandas Series repeating one value
            data=capacity,
            start=self.start,
            end=self.end,
            resolution=self.resolution,
        )

    def deserialize_config(self):
        """Do not care about any config sent in."""
        self.config_deserialized = True

    return type(
        name,
        (Scheduler,),
        {
            "__author__": "Seita",
            "__version__": "1",
            "compute": compute,
            "deserialize_config": deserialize_config,
            "fallback_scheduler_class": fallback_class,
        },
    )


SuccessfulScheduler = create_test_scheduler("SuccessfulScheduler", compute_fails=False)
FailingScheduler2 = create_test_scheduler(
    "FailingScheduler2", compute_fails=True, fallback_class=SuccessfulScheduler
)
FailingScheduler1 = create_test_scheduler(
    "FailingScheduler1", compute_fails=True, fallback_class=FailingScheduler2
)


def test_fallback_chain(
    fresh_db,
    app,
    add_battery_assets_fresh_db,
):
    """
    Check that the chaining fallback schedules works.

        FailingScheduler1 -> FailingScheduler2 -> SuccessfulScheduler
    """
    app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = True

    battery = add_battery_assets_fresh_db["Test battery"].sensors[0]
    fresh_db.session.flush()

    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 2))
    end = tz.localize(datetime(2015, 1, 3))
    resolution = timedelta(minutes=15)

    scheduler_class = FailingScheduler1

    scheduler_specs = {
        "class": scheduler_class.__name__,
        "module": inspect.getmodule(scheduler_class).__name__,
    }

    job = create_scheduling_job(
        asset_or_sensor=battery,
        start=start,
        end=end,
        belief_time=start,
        resolution=resolution,
        scheduler_specs=scheduler_specs,
    )

    for scheduler_class in ["FailingScheduler1", "FailingScheduler2"]:
        assert len(app.queues["scheduling"]) == 1
        job = app.queues["scheduling"].jobs[0]
        work_on_rq(
            app.queues["scheduling"],
            exc_handler=exception_reporter,
            max_jobs=1,
        )
        job.refresh()
        assert job.kwargs["scheduler_specs"]["class"] == scheduler_class
        assert job.is_failed
        assert isinstance(job.meta["exception"], InfeasibleProblemException)

    success_job = app.queues["scheduling"].jobs[0]
    # check that success
    work_on_rq(
        app.queues["scheduling"],
        exc_handler=exception_reporter,
        max_jobs=1,
    )
    success_job.refresh()
    assert success_job.is_finished
    assert success_job.kwargs["scheduler_specs"]["class"] == "SuccessfulScheduler"

    assert len(app.queues["scheduling"]) == 0
    app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = False


@pytest.mark.parametrize(
    "charging_eff, discharging_eff, storage_eff, expected_avg_power",
    [
        ("100%", "100%", "100%", 0.009),
        ("95%", "100%", "100%", 0.009 / 0.95),
        ("95%", "100%", "95%", 0.009 / 0.95),
        ("125%", "100%", "95%", 0.009 / 1.25),
    ],
)
def test_save_state_of_charge(
    fresh_db,
    app,
    smart_building,
    charging_eff,
    discharging_eff,
    storage_eff,
    expected_avg_power,
):
    """
    Test saving state of charge of a Heat Buffer with a constant SOC net usage of 9 kW (10kW usage and 1kW gain)
    """

    assets, sensors, soc_sensors = smart_building

    assert len(soc_sensors["Test Heat Buffer"].search_beliefs()) == 0

    queue = app.queues["scheduling"]
    start = pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam")
    end = pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam")

    scheduler_specs = {
        "module": "flexmeasures.data.models.planning.storage",
        "class": "StorageScheduler",
    }

    flex_model = {
        "power-capacity": "10kW",
        "soc-at-start": "0kWh",
        "soc-unit": "kWh",
        "soc-min": 0.0,
        "soc-max": "100kWh",
        "soc-usage": ["10kW"],
        "soc-gain": ["1kW"],
        "state-of-charge": {"sensor": soc_sensors["Test Heat Buffer"].id},
        "prefer-charging-sooner": True,
        "storage-efficiency": storage_eff,
        "charging-efficiency": charging_eff,
        "discharging-efficiency": discharging_eff,
    }

    flex_context = {
        "consumption-price": "100 EUR/MWh",
        "production-price": "0 EUR/MWh",
        "site-production-capacity": "1MW",
        "site-consumption-capacity": "1MW",
    }

    create_scheduling_job(
        asset_or_sensor=sensors["Test Heat Buffer"],
        scheduler_specs=scheduler_specs,
        flex_model=flex_model,
        flex_context=flex_context,
        enqueue=True,
        start=start,
        end=end,
        round_to_decimals=12,
        resolution=timedelta(minutes=15),
    )

    # Work on jobs
    work_on_rq(queue, handle_scheduling_exception)

    # Check that the SOC data is saved
    soc_schedule = (
        soc_sensors["Test Heat Buffer"]
        .search_beliefs(resolution=timedelta(0))
        .reset_index()
    )
    power_schedule = sensors["Test Heat Buffer"].search_beliefs().reset_index()

    power_schedule = pd.Series(
        power_schedule.event_value.tolist(),
        index=pd.DatetimeIndex(power_schedule.event_start.tolist(), freq="15min"),
    )

    assert np.isclose(
        -power_schedule.mean(), expected_avg_power
    )  # charge to cover for the net usage (in average)

    soc_schedule_from_power = integrate_time_series(
        -power_schedule,
        0.0,
        decimal_precision=16,
        stock_delta=-0.009 * 0.25,
        up_efficiency=ur.Quantity(charging_eff).to("dimensionless").magnitude,
        down_efficiency=ur.Quantity(discharging_eff).to("dimensionless").magnitude,
        storage_efficiency=ur.Quantity(storage_eff).to("dimensionless").magnitude,
    )

    assert all(
        np.isclose(soc_schedule.event_value.values, soc_schedule_from_power.values)
    )
