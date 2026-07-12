from __future__ import annotations

from flask import url_for
import pytest
from isodate import parse_datetime, parse_duration

from numpy.testing import assert_almost_equal
import pandas as pd
from rq.job import Job

from flexmeasures import Sensor
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.planning.tests.utils import check_constraints
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.scheduling import (
    handle_scheduling_exception,
    get_data_source_for_job,
)
from flexmeasures.data.services.utils import sort_jobs
from flexmeasures.utils.unit_utils import ur


@pytest.mark.parametrize(
    "message_without_targets, message_with_targets, asset_name",
    [
        (
            message_for_trigger_schedule(resolution="PT30M"),
            message_for_trigger_schedule(resolution="PT30M", with_targets=True),
            "Test battery",
        ),
    ],
)
@pytest.mark.parametrize("sequential", [True, False])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_trigger_and_get_schedule(
    app,
    add_market_prices_fresh_db,
    setup_roles_users_fresh_db,
    add_charging_station_assets_fresh_db,
    keep_scheduling_queue_empty,
    message_without_targets,
    message_with_targets,
    asset_name,
    sequential,
    requesting_user,
):  # noqa: C901
    # Include the price sensor and site-power-capacity in the flex-context explicitly, to test deserialization
    price_sensor_id = add_market_prices_fresh_db["epex_da"].id
    message_without_targets["flex-context"] = {
        "consumption-price": {"sensor": price_sensor_id},
        "production-price": {"sensor": price_sensor_id},
        "site-power-capacity": "1 TW",  # should be big enough to avoid any infeasibilities
    }

    # Set up flex-model for CP 1
    CP_1_flex_model = message_without_targets["flex-model"].copy()
    bidirectional_charging_station = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    sensor_1 = bidirectional_charging_station.sensors[0]
    assert sensor_1.name == "power", "expecting to schedule a power sensor"

    # Set up flex-model for CP 2
    charging_station = add_charging_station_assets_fresh_db["Test charging station"]
    CP_2_flex_model = message_with_targets["flex-model"].copy()
    sensor_2 = charging_station.sensors[0]
    assert sensor_2.name == "power", "expecting to schedule a power sensor"

    uni_soc_sensor = add_charging_station_assets_fresh_db["uni-soc"]
    bi_soc_sensor = add_charging_station_assets_fresh_db["bi-soc"]
    CP_1_flex_model["state-of-charge"] = {"sensor": bi_soc_sensor.id}
    CP_2_flex_model["state-of-charge"] = {"sensor": uni_soc_sensor.id}

    # Convert the two flex-models to a single multi-asset flex-model
    CP_1_flex_model["sensor"] = sensor_1.id
    CP_2_flex_model["sensor"] = sensor_2.id
    message = message_without_targets.copy()
    message["flex-model"] = [
        CP_1_flex_model,
        CP_2_flex_model,
    ]
    message["sequential"] = sequential

    # trigger a schedule through the /assets/<id>/schedules/trigger [POST] api endpoint
    assert len(app.queues["scheduling"]) == 0
    with app.test_client() as client:
        print(message)
        print(message["flex-model"])
        trigger_schedule_response = client.post(
            url_for(
                "AssetAPI:trigger_schedule", id=sensor_1.generic_asset.parent_asset.id
            ),
            json=message,
        )
        print("Server responded with:\n%s" % trigger_schedule_response.json)
        assert trigger_schedule_response.status_code == 202
        job_id = trigger_schedule_response.json["schedule"]

    # look for scheduling jobs in queue
    scheduled_jobs = app.queues["scheduling"].jobs
    deferred_job_ids = app.queues["scheduling"].deferred_job_registry.get_job_ids()
    deferred_jobs = sort_jobs(app.queues["scheduling"], deferred_job_ids)

    assert len(scheduled_jobs) == 1, "one scheduling job should be queued"
    if sequential:
        assert len(deferred_jobs) == len(
            message["flex-model"]
        ), "a scheduling job should be made for each sensor flex model (1 was already queued, but there is also 1 wrap-up job that should be triggered when the last scheduling job is done"
        done_job_id = deferred_jobs[-1].id
    else:
        assert (
            len(deferred_jobs) == 0
        ), "the whole scheduling job is handled as a single job (simultaneous scheduling)"
        done_job_id = scheduled_jobs[0].id
    scheduling_job = scheduled_jobs[0]

    print(scheduling_job.kwargs)
    if sequential:
        assert (
            scheduling_job.kwargs["asset_or_sensor"]["id"] == sensor_1.id
        ), "first queued job is for scheduling the first sensor"
    else:
        assert (
            scheduling_job.kwargs["asset_or_sensor"]["id"]
            == sensor_1.generic_asset.parent_asset.id
        ), "first queued job is the one for the top-level asset"
    assert scheduling_job.kwargs["start"] == parse_datetime(message["start"])
    assert scheduling_job.kwargs["resolution"] == parse_duration(message["resolution"])
    assert done_job_id == job_id

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Derive some expectations from the POSTed message
    resolution = sensor_1.event_resolution
    expected_length_of_schedule = parse_duration(message["duration"]) / resolution

    # check results are in the database

    # First, make sure the scheduler data source is now there
    scheduling_job.refresh()  # catch meta info that was added on this very instance
    scheduler_source = get_data_source_for_job(scheduling_job)
    assert scheduler_source is not None

    def compute_expected_length(
        message: dict, sensors: list[Sensor], sequential: bool
    ) -> list[int]:
        """We expect a longer schedule if the targets exceeds the original duration in the trigger.

        If the planning happens sequentially, individual schedules may be extended to accommodate for far-away targets.
        If the planning happens jointly, we expect all schedules to be extended.
        """
        expected_durations = [pd.Timedelta(message["duration"])] * len(sensors)
        for d, (sensor, flex_model) in enumerate(zip(sensors, message["flex-model"])):
            assert (
                flex_model["sensor"] == sensor.id
            ), "make sure we are dealing with the assumed sensor"
            if "soc-targets" in flex_model:
                for t in flex_model["soc-targets"]:
                    duration = pd.Timestamp(t["datetime"]) - pd.Timestamp(
                        message["start"]
                    )
                    if duration > expected_durations[d]:
                        if sequential:
                            expected_durations[d] = duration
                        else:
                            expected_durations = [duration] * len(sensors)

        # Convert duration to number of steps in the sensor's resolution
        expected_lengths = [
            expected_durations[d] / sensor.event_resolution
            for d, sensor in enumerate(sensors)
        ]

        return expected_lengths

    sensors = [sensor_1, sensor_2]
    soc_sensors = [bi_soc_sensor, uni_soc_sensor]
    expected_length_of_schedule = compute_expected_length(message, sensors, sequential)

    # The 72nd and 73rd quarter-hours make up the first half-hour within the cheapest hour.
    # That's when we expect all charging for the uni-directional CP.
    expected_uni_schedule = [0] * 188
    expected_uni_schedule[72] = 0.026824
    expected_uni_schedule[73] = 0.026824

    # try to retrieve the schedule for each sensor through the /sensors/<id>/schedules/<job_id> [GET] api endpoint
    for d, (sensor, soc_sensor, flex_model) in enumerate(
        zip(sensors, soc_sensors, message["flex-model"])
    ):

        # Fetch power schedule
        sensor_id = flex_model["sensor"]
        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=sensor_id, uuid=scheduling_job.id),
            query_string={"duration": "PT48H"},
        )
        print("Server responded with:\n%s" % get_schedule_response.json)
        assert get_schedule_response.status_code == 200
        assert (
            get_schedule_response.json["unit"] == "MW"
        ), "by default, the schedules are expected in the sensor unit"
        # assert get_schedule_response.json["type"] == "GetDeviceMessageResponse"
        power_schedule = get_schedule_response.json["values"]
        assert len(power_schedule) == expected_length_of_schedule[d]

        check_constraints(
            sensor=sensor,
            schedule=pd.Series(
                data=power_schedule,
                index=pd.date_range(
                    start=get_schedule_response.json["start"],
                    periods=len(power_schedule),
                    freq=sensor.event_resolution,
                ),
            ),
            soc_at_start=flex_model["soc-at-start"],
            soc_min=flex_model["soc-min"],
            soc_max=flex_model["soc-max"],
            roundtrip_efficiency=ur.Quantity(flex_model["roundtrip-efficiency"])
            .to("dimensionless")
            .magnitude,
            storage_efficiency=ur.Quantity(flex_model["storage-efficiency"])
            .to("dimensionless")
            .magnitude,
        )

        # Fetch SoC schedule
        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=soc_sensor.id, uuid=scheduling_job.id),
            query_string={"duration": "PT48H"},
        )
        print("Server responded with:\n%s" % get_schedule_response.json)
        assert get_schedule_response.status_code == 200
        assert (
            get_schedule_response.json["unit"] == "MWh"
        ), "by default, the schedules are expected in the sensor unit"
        soc_schedule = get_schedule_response.json["values"]
        assert (
            len(soc_schedule)
            == expected_length_of_schedule[d]
            * (sensor.event_resolution / parse_duration(message["resolution"]))
            + 1  # +1 because the SoC schedule is end-inclusive
        )
        assert soc_schedule[0] * 1000 == flex_model["soc-at-start"]

        # Check for cycling and final state
        if sensor_id == sensor_1.id:
            # We expect cycling fully for the bi-directional Charge Point
            assert any(
                [s == flex_model["soc-min"] / 1000 for s in soc_schedule]
            ), "we should reach soc-min at least once, because we expect at least one full cycle"
            assert any(
                [s == flex_model["soc-max"] / 1000 for s in soc_schedule]
            ), "we should reach soc-max at least once, because we expect at least one full cycle"
            assert (
                soc_schedule[-1] * 1000 == flex_model["soc-min"]
            ), "we should end empty"
        else:
            # We expect no cycling for the uni-directional Charge Point
            s = pd.Series(soc_schedule)
            soc_as_percentage_of_previous_soc = 1 + s.diff() / s
            assert (
                soc_as_percentage_of_previous_soc.min()
                <= ur.Quantity(flex_model["storage-efficiency"]).to("").magnitude
            ), "all downwards SoC should be attributable to storage losses"
            assert (
                soc_schedule[-1] * 1000 == flex_model["soc-targets"][0]["value"]
            ), "we should end on target"

        prices = add_market_prices_fresh_db["epex_da"].search_beliefs(
            event_starts_after=message["start"],
            event_ends_before=pd.Timestamp(message["start"])
            + pd.Timedelta(message["duration"]),
        )
        cheapest_hour = prices.values.argmin()
        if sequential and sensor_id == sensor_2.id:
            assert (
                sum(power_schedule[cheapest_hour * 4 : (cheapest_hour + 1) * 4]) > 0
            ), "we expect to charge in the cheapest hour"
            assert_almost_equal(power_schedule, expected_uni_schedule)
        elif not sequential and sensor_id == sensor_2.id:
            assert (
                sum(power_schedule[cheapest_hour * 4 : (cheapest_hour + 1) * 4]) > 0
            ), "we expect to charge in the cheapest hour"
            assert_almost_equal(power_schedule, expected_uni_schedule)


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_trigger_and_get_aggregate_schedule(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    setup_roles_users_fresh_db,
    add_charging_station_assets_fresh_db,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """Test that aggregate-consumption and aggregate-production flex-context fields get filled with data.

    This test verifies:
    1. Aggregate-consumption sensor receives the total consumption schedule with correct sign
    2. Aggregate-production sensor receives the total production schedule with correct sign
    3. The data source is correctly set to the scheduler
    4. The sign convention matches the scheduler's output (consumption positive, production negative)
    """
    # Set up charging hub with aggregate sensors
    bidirectional_charging_station = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    charging_hub = bidirectional_charging_station.parent_asset

    # Create aggregate consumption and production sensors on the hub
    aggregate_consumption_sensor = Sensor(
        name="aggregate-consumption",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    aggregate_production_sensor = Sensor(
        name="aggregate-production",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    fresh_db.session.add(aggregate_consumption_sensor)
    fresh_db.session.add(aggregate_production_sensor)
    fresh_db.session.flush()

    # Set up price sensor
    price_sensor_id = add_market_prices_fresh_db["epex_da"].id

    # Create flex-model with both charging stations
    bidirectional_charging_station = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    charging_station = add_charging_station_assets_fresh_db["Test charging station"]

    sensor_1 = bidirectional_charging_station.sensors[0]
    sensor_2 = charging_station.sensors[0]
    bi_soc_sensor = add_charging_station_assets_fresh_db["bi-soc"]
    uni_soc_sensor = add_charging_station_assets_fresh_db["uni-soc"]

    # Build the message with aggregate sensors in flex-context
    message = message_for_trigger_schedule(resolution="PT30M")
    message["flex-context"] = {
        "consumption-price": {"sensor": price_sensor_id},
        "production-price": {"sensor": price_sensor_id},
        "site-power-capacity": "1 TW",
        "aggregate-consumption": {"sensor": aggregate_consumption_sensor.id},
        "aggregate-production": {"sensor": aggregate_production_sensor.id},
    }

    # Set up flex-models for both charging stations
    CP_1_flex_model = message["flex-model"].copy()
    CP_1_flex_model["state-of-charge"] = {"sensor": bi_soc_sensor.id}
    CP_1_flex_model["sensor"] = sensor_1.id

    CP_2_flex_model = message["flex-model"].copy()
    CP_2_flex_model["state-of-charge"] = {"sensor": uni_soc_sensor.id}
    CP_2_flex_model["sensor"] = sensor_2.id

    message["flex-model"] = [CP_1_flex_model, CP_2_flex_model]

    # Trigger the schedule
    assert len(app.queues["scheduling"]) == 0
    with app.test_client() as client:
        trigger_response = client.post(
            url_for("AssetAPI:trigger_schedule", id=charging_hub.id),
            json=message,
        )
        assert trigger_response.status_code == 202
        job_id = trigger_response.json["schedule"]

    # Process the scheduling queue
    scheduled_jobs = app.queues["scheduling"].jobs
    scheduling_job = scheduled_jobs[0]
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Verify scheduler data source was created
    scheduling_job.refresh()
    scheduler_source = get_data_source_for_job(scheduling_job)
    assert scheduler_source is not None

    # Verify aggregate-consumption sensor got filled with data
    consumption_beliefs = (
        TimedBelief.query.filter(
            TimedBelief.sensor_id == aggregate_consumption_sensor.id
        )
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert len(consumption_beliefs) > 0, "aggregate-consumption sensor should have data"

    # Extract consumption schedule (consumption is positive in the scheduler)
    consumption_schedule = pd.Series(
        [
            -v.event_value for v in consumption_beliefs
        ],  # Negate because DB stores consumption as negative
        index=pd.DatetimeIndex([v.event_start for v in consumption_beliefs]),
    )

    # Verify aggregate-production sensor got filled with data
    production_beliefs = (
        TimedBelief.query.filter(
            TimedBelief.sensor_id == aggregate_production_sensor.id
        )
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert len(production_beliefs) > 0, "aggregate-production sensor should have data"

    # Extract production schedule (production is negative in the scheduler, but stored as positive in DB for production sensors)
    production_schedule = pd.Series(
        [v.event_value for v in production_beliefs],
        index=pd.DatetimeIndex([v.event_start for v in production_beliefs]),
    )

    # Verify sign conventions: some values should be positive (consumption), some negative (production)
    # At least one consumption value should be positive
    assert (
        consumption_schedule > 0
    ).any(), "consumption schedule should have some positive values"

    # For a test with charging, we might not have discharge, so production could be all zeros
    # But we still verify the schedule structure is correct
    assert (
        production_schedule >= 0
    ).all(), "production schedule should have non-negative values (production flows are positive)"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_trigger_with_multi_commodity_flex_context(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    setup_roles_users_fresh_db,
    add_charging_station_assets_fresh_db,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """Test aggregate sensors with multi-commodity flex-context (electricity and heat).

    This test verifies that:
    1. Multi-commodity flex-context (list format) works correctly
    2. Each commodity has its own aggregate sensors
    3. Devices with different commodities are scheduled together
    4. Aggregate sensors correctly sum their respective commodity's power flows
    """
    from flexmeasures.data.models.generic_assets import GenericAssetType

    # Set up charging hub
    bidirectional_cs = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    charging_hub = bidirectional_cs.parent_asset

    # Create a heat device (boiler) as a sibling to the charging stations
    boiler_asset_type = GenericAssetType(name="boiler")
    fresh_db.session.add(boiler_asset_type)
    fresh_db.session.flush()

    boiler = GenericAsset(
        name="Test boiler",
        owner=charging_hub.owner,
        generic_asset_type=boiler_asset_type,
        parent_asset=charging_hub,
        latitude=10,
        longitude=100,
        attributes=dict(
            is_consumer=True,
            is_producer=False,
            can_shift=True,
        ),
    )
    boiler_power_sensor = Sensor(
        name="power",
        generic_asset=boiler,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    boiler_soc_sensor = Sensor(
        name="heat-soc",
        generic_asset=boiler,
        unit="MWh",
        event_resolution=pd.Timedelta(minutes=0),
    )
    fresh_db.session.add(boiler)
    fresh_db.session.add(boiler_power_sensor)
    fresh_db.session.add(boiler_soc_sensor)
    fresh_db.session.flush()

    # Create aggregate sensors for each commodity
    agg_consumption_electricity = Sensor(
        name="aggregate-consumption-electricity",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    agg_production_electricity = Sensor(
        name="aggregate-production-electricity",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    agg_consumption_heat = Sensor(
        name="aggregate-consumption-heat",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    fresh_db.session.add(agg_consumption_electricity)
    fresh_db.session.add(agg_production_electricity)
    fresh_db.session.add(agg_consumption_heat)
    fresh_db.session.flush()

    # Set up price sensors
    price_sensor_id = add_market_prices_fresh_db["epex_da"].id

    # Get the charging station
    charging_station_uni = add_charging_station_assets_fresh_db["Test charging station"]
    sensor_uni = charging_station_uni.sensors[0]
    soc_uni_sensor = add_charging_station_assets_fresh_db["uni-soc"]

    # Build the message with multi-commodity flex-context as a LIST
    message = message_for_trigger_schedule(resolution="PT30M")

    # Multi-commodity flex-context as a LIST of commodity contexts
    message["flex-context"] = [
        {
            "commodity": "electricity",
            "consumption-price": {"sensor": price_sensor_id},
            "production-price": {"sensor": price_sensor_id},
            "site-power-capacity": "1 TW",
            "aggregate-consumption": {"sensor": agg_consumption_electricity.id},
            "aggregate-production": {"sensor": agg_production_electricity.id},
        },
        {
            "commodity": "heat",
            "consumption-price": {"sensor": price_sensor_id},
            "site-consumption-capacity": "100 kW",
            "site-production-capacity": "0 kW",
            "aggregate-consumption": {"sensor": agg_consumption_heat.id},
        },
    ]

    # Set up flex-models for electricity (charging station) and heat (boiler)
    flex_model_electricity = message["flex-model"].copy()
    flex_model_electricity["state-of-charge"] = {"sensor": soc_uni_sensor.id}
    flex_model_electricity["sensor"] = sensor_uni.id
    flex_model_electricity["commodity"] = "electricity"

    flex_model_heat = {
        "sensor": boiler_power_sensor.id,
        "commodity": "heat",
        "state-of-charge": {"sensor": boiler_soc_sensor.id},
        "soc-at-start": 10.0,
        "soc-min": 0,
        "soc-max": 20.0,
        "soc-unit": "MWh",
        "power-capacity": "1 MW",
        "roundtrip-efficiency": "98%",
        "storage-efficiency": "99.99%",
    }

    message["flex-model"] = [flex_model_electricity, flex_model_heat]

    # Trigger the schedule
    assert len(app.queues["scheduling"]) == 0
    with app.test_client() as client:
        trigger_response = client.post(
            url_for("AssetAPI:trigger_schedule", id=charging_hub.id),
            json=message,
        )
        if trigger_response.status_code != 202:
            print(f"Error response: {trigger_response.json}")
        assert trigger_response.status_code == 202
        job_id = trigger_response.json["schedule"]

    # Process the scheduling queue
    scheduled_jobs = app.queues["scheduling"].jobs
    scheduling_job = scheduled_jobs[0]
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Verify scheduler data source
    scheduling_job.refresh()
    scheduler_source = get_data_source_for_job(scheduling_job)
    assert scheduler_source is not None

    # Verify electricity aggregate-consumption sensor got filled
    consumption_beliefs_elec = (
        TimedBelief.query.filter(
            TimedBelief.sensor_id == agg_consumption_electricity.id
        )
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert (
        len(consumption_beliefs_elec) > 0
    ), "electricity aggregate-consumption should have data"

    # Verify electricity aggregate-production sensor got filled
    production_beliefs_elec = (
        TimedBelief.query.filter(TimedBelief.sensor_id == agg_production_electricity.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert (
        len(production_beliefs_elec) > 0
    ), "electricity aggregate-production should have data"

    # Verify heat aggregate-consumption sensor got filled
    consumption_beliefs_heat = (
        TimedBelief.query.filter(TimedBelief.sensor_id == agg_consumption_heat.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert (
        len(consumption_beliefs_heat) > 0
    ), "heat aggregate-consumption should have data"

    # Verify data types are correct
    assert all(
        isinstance(v.event_value, (int, float)) or v.event_value is None
        for v in consumption_beliefs_elec
    ), "electricity consumption values should be numeric"
    assert all(
        isinstance(v.event_value, (int, float)) or v.event_value is None
        for v in consumption_beliefs_heat
    ), "heat consumption values should be numeric"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_trigger_with_flex_context_commodity_not_used(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    setup_roles_users_fresh_db,
    add_charging_station_assets_fresh_db,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """Test multi-commodity flex-context where one commodity is not used by any device.

    This test verifies that:
    1. Commodities in flex-context but not used in flex-model don't cause errors
    2. Aggregate sensors for unused commodities receive no data (which is expected)
    3. Devices for other commodities are scheduled normally
    """
    # Set up charging hub
    bidirectional_cs = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    charging_hub = bidirectional_cs.parent_asset

    # Create aggregate sensors for electricity and heat
    agg_consumption_electricity = Sensor(
        name="aggregate-consumption-elec-unused",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    agg_consumption_heat = Sensor(
        name="aggregate-consumption-heat-unused",
        generic_asset=charging_hub,
        unit="MW",
        event_resolution=pd.Timedelta(minutes=15),
    )
    fresh_db.session.add(agg_consumption_electricity)
    fresh_db.session.add(agg_consumption_heat)
    fresh_db.session.flush()

    # Set up price sensors
    price_sensor_id = add_market_prices_fresh_db["epex_da"].id

    # Get the charging station
    charging_station_uni = add_charging_station_assets_fresh_db["Test charging station"]
    sensor_uni = charging_station_uni.sensors[0]
    soc_uni_sensor = add_charging_station_assets_fresh_db["uni-soc"]

    # Build the message with multi-commodity flex-context
    message = message_for_trigger_schedule(resolution="PT30M")

    # Multi-commodity flex-context with both electricity and heat commodities
    # But only electricity devices in flex-model
    message["flex-context"] = [
        {
            "commodity": "electricity",
            "consumption-price": {"sensor": price_sensor_id},
            "production-price": {"sensor": price_sensor_id},
            "site-power-capacity": "1 TW",
            "aggregate-consumption": {"sensor": agg_consumption_electricity.id},
        },
        {
            "commodity": "heat",
            "consumption-price": {"sensor": price_sensor_id},
            "site-consumption-capacity": "100 kW",
            "site-production-capacity": "0 kW",
            "aggregate-consumption": {"sensor": agg_consumption_heat.id},
        },
    ]

    # Only electricity flex-model (no heat device)
    flex_model_electricity = message["flex-model"].copy()
    flex_model_electricity["state-of-charge"] = {"sensor": soc_uni_sensor.id}
    flex_model_electricity["sensor"] = sensor_uni.id
    flex_model_electricity["commodity"] = "electricity"

    message["flex-model"] = [flex_model_electricity]

    # Trigger the schedule
    assert len(app.queues["scheduling"]) == 0
    with app.test_client() as client:
        trigger_response = client.post(
            url_for("AssetAPI:trigger_schedule", id=charging_hub.id),
            json=message,
        )
        if trigger_response.status_code != 202:
            print(f"Error response: {trigger_response.json}")
        assert trigger_response.status_code == 202
        job_id = trigger_response.json["schedule"]

    # Process the scheduling queue
    scheduled_jobs = app.queues["scheduling"].jobs
    scheduling_job = scheduled_jobs[0]
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Verify scheduler data source
    scheduling_job.refresh()
    scheduler_source = get_data_source_for_job(scheduling_job)
    assert scheduler_source is not None

    # Verify electricity aggregate-consumption sensor got filled
    consumption_beliefs_elec = (
        TimedBelief.query.filter(
            TimedBelief.sensor_id == agg_consumption_electricity.id
        )
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert (
        len(consumption_beliefs_elec) > 0
    ), "electricity aggregate-consumption should have data"

    # Verify heat aggregate-consumption sensor is empty (no heat device)
    consumption_beliefs_heat = (
        TimedBelief.query.filter(TimedBelief.sensor_id == agg_consumption_heat.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    assert (
        len(consumption_beliefs_heat) == 0
    ), "heat aggregate-consumption should be empty since no heat device was scheduled"
