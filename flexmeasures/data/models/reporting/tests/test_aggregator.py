import pytest
from marshmallow import ValidationError

from flexmeasures.data.models.reporting.aggregator import AggregatorReporter
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import save_to_db
from datetime import datetime, timedelta
from pytz import utc, timezone

import pandas as pd


@pytest.mark.parametrize(
    "aggregation_method, expected_value",
    [
        ("sum", 0),
        ("mean", 0),
        ("var", 2),
        ("std", 2**0.5),
        ("max", 1),
        ("min", -1),
        ("prod", -1),
        ("median", 0),
    ],
)
def test_aggregator(setup_dummy_data, aggregation_method, expected_value, db):
    """
    This test computes the aggregation of two sensors containing 24 entries
    with value 1 and -1, respectively, for sensors 1 and 2.

    Test cases:
        1) sum: 0 = 1 + (-1)
        2) mean: 0 = ((1) + (-1))/2
        3) var: 2 = (1)^2 + (-1)^2
        4) std: sqrt(2) = sqrt((1)^2 + (-1)^2)
        5) max: 1 = max(1, -1)
        6) min: -1 = min(1, -1)
        7) prod: -1 = (1) * (-1)
        8) median: even number of elements, mean of the most central elements, 0 = ((1) + (-1))/2
    """
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter(method=aggregation_method)

    source_1 = db.session.get(DataSource, 1)
    source_2 = db.session.get(DataSource, 2)

    result = agg_reporter.compute(
        input=[dict(sensor=s1, source=source_1), dict(sensor=s2, source=source_2)],
        output=[dict(sensor=report_sensor)],
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )[0]["data"]

    # check that we got a result for 24 hours
    assert len(result) == 24

    # check that the value is equal to expected_value
    assert (result == expected_value).all().event_value


@pytest.mark.parametrize(
    "weight_1, weight_2, expected_result",
    [(1, 1, 0), (1, -1, 2), (2, 0, 2), (0, 2, -2)],
)
def test_aggregator_reporter_weights(
    setup_dummy_data, weight_1, weight_2, expected_result, db
):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    reporter_config = dict(method="sum", weights={"s1": weight_1, "sensor_2": weight_2})

    source_1 = db.session.get(DataSource, 1)
    source_2 = db.session.get(DataSource, 2)

    agg_reporter = AggregatorReporter(config=reporter_config)

    result = agg_reporter.compute(
        input=[
            dict(name="s1", sensor=s1, source=source_1),
            dict(sensor=s2, source=source_2),
        ],
        output=[dict(sensor=report_sensor)],
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )[0]["data"]

    # check that we got a result for 24 hours
    assert len(result) == 24

    # check that the value is equal to expected_value
    assert (result == expected_result).all().event_value


def test_dst_transition(setup_dummy_data, db):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter()

    tz = timezone("Europe/Amsterdam")

    # transition from winter (CET) to summer (CEST)
    result = agg_reporter.compute(
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=report_sensor)],
        start=tz.localize(datetime(2023, 3, 26)),
        end=tz.localize(datetime(2023, 3, 27)),
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 23

    # transition from summer (CEST) to winter (CET)
    result = agg_reporter.compute(
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=report_sensor)],
        start=tz.localize(datetime(2023, 10, 29)),
        end=tz.localize(datetime(2023, 10, 30)),
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 25


def test_resampling(setup_dummy_data, db):
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter()

    tz = timezone("Europe/Amsterdam")

    # transition from winter (CET) to summer (CEST)
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 3, 27)),
        end=tz.localize(datetime(2023, 3, 28)),
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=daily_report_sensor, source=db.session.get(DataSource, 1))],
        belief_time=tz.localize(datetime(2023, 12, 1)),
        resolution=pd.Timedelta("1D"),
    )[0]["data"]

    assert result.event_starts[0] == pd.Timestamp(
        year=2023, month=3, day=27, tz="Europe/Amsterdam"
    )

    # transition from summer (CEST) to winter (CET)
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 10, 29)),
        end=tz.localize(datetime(2023, 10, 30)),
        input=[dict(sensor=s3, source=db.session.get(DataSource, 1))],
        output=[dict(sensor=daily_report_sensor, source=db.session.get(DataSource, 1))],
        belief_time=tz.localize(datetime(2023, 12, 1)),
        resolution=pd.Timedelta("1D"),
    )[0]["data"]

    assert result.event_starts[0] == pd.Timestamp(
        year=2023, month=10, day=29, tz="Europe/Amsterdam"
    )


def test_source_transition(setup_dummy_data, db):
    """The first 13 hours of the time window "belong" to Source 1 and are filled with 1.0.
    From 12:00 to 24:00, there are events belonging to Source 2 with value -1.

    We expect the reporter to use only the values defined in the `sources` array in the `input` field.
    In case of encountering more than one source per event, the first source defined in the sources
    array is prioritized.

    """
    s1, s2, s3, s4, report_sensor, daily_report_sensor = setup_dummy_data

    agg_reporter = AggregatorReporter()

    tz = timezone("UTC")

    ds1 = db.session.get(DataSource, 1)
    ds2 = db.session.get(DataSource, 2)

    # considering DataSource 1 and 2
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds1, ds2])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 24
    assert (
        (result[:13] == 1).all().event_value
    )  # the data from the first source is used
    assert (result[13:] == -1).all().event_value

    # Naming the sources the other way round hands the overlapping event to the other source,
    # which is what "the first source defined in the sources array" means.
    reversed_result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds2, ds1])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]
    assert (reversed_result[:12] == 1).all().event_value
    assert (reversed_result[12:] == -1).all().event_value

    # only considering DataSource 1
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds1])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 13
    assert (result == 1).all().event_value

    # only considering DataSource 2
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, sources=[ds2])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 12
    assert (result == -1).all().event_value

    # if no source is passed, the reporter should raise a ValueError
    # as there are events with different data sources in the report time period.
    # This is important, for instance, for sensors containing power and scheduled values
    # where we could get beliefs from both sources.
    with pytest.raises(ValueError):
        result = agg_reporter.compute(
            start=tz.localize(datetime(2023, 4, 24)),
            end=tz.localize(datetime(2023, 4, 25)),
            input=[dict(sensor=s3)],
            output=[dict(sensor=report_sensor)],
            belief_time=tz.localize(datetime(2023, 12, 1)),
        )[0]["data"]

    # The exception to the above is when a new version of the same source recorded a value,
    # in which case the latest version takes precedence. This happened in the last hour of the day.
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3)],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert (result[:5] == -1).all().event_value  # beliefs from the older version
    assert (result[5:] == 3).all().event_value  # belief from the latest version

    # If we exclude source type "A" (source 1 is of that type) we should get the same result.
    same_result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, exclude_source_types=["A"])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert (same_result == result).all().event_value

    # If we exclude source type "B" (both versions of source 2 are of that type) we should get an empty result
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, exclude_source_types=["B"])],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert result.empty

    # If we set use_latest_version_per_event=False, we should get both versions of source 2,
    # and one_deterministic_belief_per_event=True kicks in to give back the most recent version
    result = agg_reporter.compute(
        start=tz.localize(datetime(2023, 4, 24, 18, 0)),
        end=tz.localize(datetime(2023, 4, 25)),
        input=[dict(sensor=s3, use_latest_version_per_event=False)],
        output=[dict(sensor=report_sensor)],
        belief_time=tz.localize(datetime(2023, 12, 1)),
    )[0]["data"]

    assert len(result) == 6
    assert (result[:5] == -1).all().event_value  # beliefs from the older version
    assert (result[5:] == 3).all().event_value  # belief from the latest version


def test_aggregate_a_pv_group(setup_pv_group, db):
    """Felix's worked example: a group of two PV installations, aggregated onto the group's own sensor.

    The roof records 400 kW quarter-hourly and the carport 0.15 MW hourly,
    so the group's aggregate is 0.55 MW for every quarter-hour of the day,
    with kW converted to MW and the hourly values carried across their own hour.
    Nothing in the report's config says which sensors those are.
    """
    farm, pv_group, aggregate_sensor, roof_power, carport_power, temperature, _, _ = (
        setup_pv_group
    )

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})

    assert sorted(sensor.id for sensor in reporter.input_sensors) == sorted(
        [roof_power.id, carport_power.id]
    )
    assert [sensor.id for sensor in reporter.output_sensors] == [aggregate_sensor.id]

    result = reporter.compute(
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )

    assert result[0]["sensor"].id == aggregate_sensor.id
    assert len(result[0]["data"]) == 96
    assert result[0]["data"]["event_value"].values == pytest.approx(0.55)


def test_group_leaves_out_the_weather_sensor(setup_pv_group, db):
    """The temperature sensor sits in the group's subtree but declares no membership, so it is not aggregated."""
    _, pv_group, _, _, _, temperature, _, _ = setup_pv_group

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})

    assert temperature.id not in [sensor.id for sensor in reporter.input_sensors]


def test_group_leaves_out_its_own_aggregate_sensor(setup_pv_group, db, temp_assets):
    """A member that names the group's own aggregate sensor is not read back in as input.

    This is the double-counting case: the aggregate sensor already holds 42 MW of scheduled values,
    so reading it in as well would make the aggregate 42.55 rather than 0.55.
    """
    _, pv_group, aggregate_sensor, _, _, _, _, _ = setup_pv_group

    # a third member that (wrongly) declares the group's own aggregate sensor as its power sensor
    double_counter = GenericAsset(
        name="Double counter",
        generic_asset_type=pv_group.generic_asset_type,
        parent_asset=pv_group,
    )
    db.session.add(double_counter)
    temp_assets.append(double_counter)
    db.session.flush()
    double_counter.flex_model = {
        "inflexible-production": {"sensor": aggregate_sensor.id},
        "group": {"asset": pv_group.id},
    }
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})

    assert aggregate_sensor.id not in [sensor.id for sensor in reporter.input_sensors]

    result = reporter.compute(
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # 0.55, not 42.55
    assert result["event_value"].values == pytest.approx(0.55)


def test_group_membership_is_what_drives_the_report(
    setup_pv_group, db, restore_flex_models
):
    """Only the entries that declare the group are aggregated, which is what makes the flex-config the source of truth."""
    _, pv_group, _, roof_power, carport_power, _, roof, _ = setup_pv_group

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})
    assert sorted(s.id for s in reporter.input_sensors) == sorted(
        [roof_power.id, carport_power.id]
    )

    # take the roof out of the group, and the report follows
    restore_flex_models(roof)
    roof.flex_model = {"inflexible-production": {"sensor": roof_power.id}}
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})
    assert [s.id for s in reporter.input_sensors] == [carport_power.id]

    result = reporter.compute(
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]
    assert result["event_value"].values == pytest.approx(0.15)


def test_energy_output_sums_over_a_longer_event(setup_pv_group, db, temp_assets):
    """An energy aggregate adds its finer events up, where a power aggregate would average them.

    Four quarter-hourly 1 kWh events are 4 kWh in the hour, i.e. 0.004 MWh.
    """
    _, pv_group, _, _, _, _, _, _ = setup_pv_group

    meter_asset = GenericAsset(
        name="Energy meter (stock)",
        generic_asset_type=pv_group.generic_asset_type,
        parent_asset=pv_group,
    )
    db.session.add(meter_asset)
    temp_assets.append(meter_asset)
    db.session.flush()
    quarter_hourly_energy = Sensor(
        "energy",
        generic_asset=meter_asset,
        event_resolution=timedelta(minutes=15),
        unit="kWh",
        timezone="UTC",
    )
    hourly_energy = Sensor(
        "hourly energy",
        generic_asset=meter_asset,
        event_resolution=timedelta(hours=1),
        unit="MWh",
        timezone="UTC",
    )
    db.session.add_all([quarter_hourly_energy, hourly_energy])
    db.session.flush()
    source = db.session.execute(
        db.select(DataSource).filter_by(name="pv measurements")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 6, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=1,
                sensor=quarter_hourly_energy,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    reporter = AggregatorReporter(config={"method": "sum"})
    result = reporter.compute(
        input=[dict(sensor=quarter_hourly_energy)],
        output=[dict(sensor=hourly_energy)],
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    assert len(result) == 24
    assert result["event_value"].values == pytest.approx(0.004)


def test_hourly_sensor_carried_across_a_finer_output(setup_pv_group, db):
    """A power recorded hourly holds through its hour, so it fills every quarter of a 15-minute output."""
    _, pv_group, aggregate_sensor, _, carport_power, _, _, _ = setup_pv_group

    reporter = AggregatorReporter(config={"method": "sum"})
    result = reporter.compute(
        input=[dict(sensor=carport_power)],
        output=[dict(sensor=aggregate_sensor)],
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # every quarter-hour of the day is filled, none left empty by the upsampling
    assert len(result) == 96
    assert result["event_value"].values == pytest.approx(0.15)


def test_group_realized_report_excludes_a_forecast(setup_pv_group, db):
    """A realized aggregate asks for beliefs formed after the fact, so the roof's 12-hour-ahead forecast is left out.

    The roof holds a measurement of 400 kW and a forecast of 999 kW for every event.
    Asking for a horizon of at most zero keeps only the measurement, so the aggregate is 0.55 MW
    rather than the 1.149 MW the forecast would make it.
    """
    _, pv_group, _, _, _, _, _, _ = setup_pv_group

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})

    realized = reporter.compute(
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]
    assert realized["event_value"].values == pytest.approx(0.55)

    # Note: a *forecast* aggregate is not simply the same report with a longer horizon.
    # `horizons_at_most` is an upper bound, so a longer horizon still admits the measurement,
    # and the most recent belief per event wins. Selecting the forecast would need a lower
    # bound (`horizons_at_least`) in the report parameters, which this reporter does not expose yet.
    still_realized = reporter.compute(
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(hours=12),
    )[0]["data"]
    assert still_realized["event_value"].values == pytest.approx(0.55)


def test_group_members_filtered_by_asset_type(setup_pv_group, db):
    """A members filter picks a category out of a group, here only the solar assets."""
    farm, pv_group, _, roof_power, carport_power, _, _, _ = setup_pv_group

    reporter = AggregatorReporter(
        config={
            "group": {"asset": pv_group.id},
            "members": {"asset-type": "PvGroupSolar"},
        }
    )
    assert sorted(sensor.id for sensor in reporter.input_sensors) == sorted(
        [roof_power.id, carport_power.id]
    )

    reporter = AggregatorReporter(
        config={
            "group": {"asset": pv_group.id},
            "members": {"asset-type": "PvGroupWeather"},
        }
    )
    assert reporter.input_sensors == []


def test_group_adding_a_member_needs_no_report_change(setup_pv_group, db, temp_assets):
    """Adding a PV installation to the group adds it to the report, with nothing to keep in sync."""
    farm, pv_group, aggregate_sensor, _, _, _, _, _ = setup_pv_group

    extra_asset = GenericAsset(
        name="Shed PV",
        generic_asset_type=pv_group.generic_asset_type,
        parent_asset=pv_group,
    )
    db.session.add(extra_asset)
    temp_assets.append(extra_asset)
    db.session.flush()
    extra_sensor = Sensor(
        "power",
        generic_asset=extra_asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="UTC",
    )
    db.session.add(extra_sensor)
    db.session.flush()
    extra_asset.flex_model = {
        "inflexible-production": {"sensor": extra_sensor.id},
        "group": {"asset": pv_group.id},
    }
    source = db.session.execute(
        db.select(DataSource).filter_by(name="pv measurements")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 6, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=100,
                sensor=extra_sensor,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    # the very same reporter config as before
    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})
    result = reporter.compute(
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # 0.55 + 0.1 MW
    assert result["event_value"].values == pytest.approx(0.65)


def test_group_refuses_an_incomparable_member(setup_pv_group, db, restore_flex_models):
    """A member recording something other than power cannot be added to a power aggregate."""
    _, pv_group, _, _, _, temperature, _, _ = setup_pv_group

    weather_asset = restore_flex_models(temperature.generic_asset)
    weather_asset.flex_model = {
        "inflexible-production": {"sensor": temperature.id},
        "group": {"asset": pv_group.id},
    }
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})
    with pytest.raises(ValueError, match="°C"):
        reporter.compute(
            start=datetime(2026, 6, 1, tzinfo=utc),
            end=datetime(2026, 6, 2, tzinfo=utc),
            belief_horizon=timedelta(0),
        )


def test_group_without_an_aggregate_sensor(setup_pv_group, db, restore_flex_models):
    """A group whose entry says nowhere to record the aggregate is reported as such."""
    _, pv_group, aggregate_sensor, _, _, _, _, _ = setup_pv_group

    restore_flex_models(pv_group)
    pv_group.flex_model = {}
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})
    with pytest.raises(
        ValueError, match="does not say where its aggregate is recorded"
    ):
        reporter.compute(
            start=datetime(2026, 6, 1, tzinfo=utc),
            end=datetime(2026, 6, 2, tzinfo=utc),
            belief_horizon=timedelta(0),
        )


def test_members_filter_needs_a_group(db, app):
    """A members filter has nothing to narrow without a group."""
    with pytest.raises(ValidationError, match="needs a `group`"):
        AggregatorReporter(config={"members": {"asset-type": "solar"}})


def test_aggregator_without_any_output(setup_dummy_data, db):
    """Without a group and without an output parameter, there is nowhere to record the report."""
    s1, s2, *_ = setup_dummy_data

    reporter = AggregatorReporter(config={"method": "sum"})
    with pytest.raises(ValueError, match="no sensor to record its report on"):
        reporter.compute(
            input=[dict(sensor=s1)],
            start=datetime(2023, 5, 10, tzinfo=utc),
            end=datetime(2023, 5, 11, tzinfo=utc),
        )


def test_energy_sensor_converted_at_its_own_resolution(setup_pv_group, db, temp_assets):
    """Converting a stock to a flow divides by the duration of an event, so the sensor's own resolution has to be used.

    Four quarter-hourly 1 kWh events are 4 kW each, i.e. 0.004 MW on average over the hour.
    Converting as though the data were already hourly gives 0.001 MW, which was the bug.
    """
    farm, pv_group, _, _, _, _, _, _ = setup_pv_group

    energy_asset = GenericAsset(
        name="Energy meter",
        generic_asset_type=pv_group.generic_asset_type,
        parent_asset=pv_group,
    )
    db.session.add(energy_asset)
    temp_assets.append(energy_asset)
    db.session.flush()
    energy_sensor = Sensor(
        "energy",
        generic_asset=energy_asset,
        event_resolution=timedelta(minutes=15),
        unit="kWh",
        timezone="UTC",
    )
    hourly_output = Sensor(
        "hourly power",
        generic_asset=energy_asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
        timezone="UTC",
    )
    db.session.add_all([energy_sensor, hourly_output])
    db.session.flush()
    source = db.session.execute(
        db.select(DataSource).filter_by(name="pv measurements")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 6, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=1,
                sensor=energy_sensor,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    reporter = AggregatorReporter(config={"method": "sum"})
    result = reporter.compute(
        input=[dict(sensor=energy_sensor)],
        output=[dict(sensor=hourly_output)],
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    assert result["event_value"].values == pytest.approx(0.004)


def test_nested_group_resolves_to_its_leaf_devices(setup_nested_groups, db):
    """A group of groups is aggregated from the devices behind it, not from the inner groups' own output sensors."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    reporter = AggregatorReporter(config={"group": {"asset": street.id}})

    read = sorted(sensor.id for sensor in reporter.input_sensors)
    assert read == sorted([pv_power.id, hp_power.id, far_power.id])
    # the house's own output sensor is a group's aggregate, not a device, so it is not read
    assert house_total.id not in read

    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )

    assert result[0]["sensor"].id == street_total.id
    # recorded under `production`, so production is positive: 100 kW + 60 kW of PV, minus 40 kW of heat pump
    assert result[0]["data"]["event_value"].values == pytest.approx(0.12)


def test_nested_group_member_outside_the_subtree(setup_nested_groups, db):
    """A device that joins a group from elsewhere below the site is aggregated, as the scheduler counts it."""
    region, street, *_, far_power = setup_nested_groups

    reporter = AggregatorReporter(config={"group": {"asset": street.id}})

    assert far_power.id in [sensor.id for sensor in reporter.input_sensors]
    assert far_power.generic_asset.parent_asset.id == region.id
    assert far_power.generic_asset.parent_asset.id != street.id


def test_nested_group_filtered_to_solar_members(setup_nested_groups, db):
    """Filtering a group of groups by asset type reaches the leaf devices, so the street's PV is found."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    reporter = AggregatorReporter(
        config={
            "group": {"asset": street.id},
            "members": {"asset-type": "NestedSolar"},
        }
    )

    assert sorted(sensor.id for sensor in reporter.input_sensors) == sorted(
        [pv_power.id, far_power.id]
    )

    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # only the PV: 100 kW + 60 kW
    assert result["event_value"].values == pytest.approx(0.16)


def test_split_member_contributes_both_halves(setup_nested_groups, db, temp_assets):
    """A device recording consumption and production on two sensors has both read, with opposite signs."""
    region, street, house, street_total, *_ = setup_nested_groups

    split = GenericAsset(
        name="Split device",
        generic_asset_type=street.generic_asset_type,
        parent_asset=house,
    )
    db.session.add(split)
    temp_assets.append(split)
    db.session.flush()
    cons = Sensor(
        "split consumption",
        generic_asset=split,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="UTC",
    )
    prod = Sensor(
        "split production",
        generic_asset=split,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="UTC",
    )
    db.session.add_all([cons, prod])
    db.session.flush()
    split.flex_model = {
        "consumption": {"sensor": cons.id},
        "production": {"sensor": prod.id},
        "group": {"asset": house.id},
    }
    source = db.session.execute(
        db.select(DataSource).filter_by(name="nested meter")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 7, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=value,
                sensor=sens,
                source=source,
            )
            for sens, value in ((cons, 10), (prod, 25))
            for event in range(96)
        ]
    )
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": street.id}})
    read = [sensor.id for sensor in reporter.input_sensors]
    assert cons.id in read and prod.id in read

    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # 0.12 from before, plus 25 kW produced and 10 kW consumed
    assert result["event_value"].values == pytest.approx(0.135)


def test_plain_power_sensor_is_production_positive_by_default(
    setup_nested_groups, db, temp_assets
):
    """A device given as a plain power sensor follows the platform's production-positive default.

    A battery without the `consumption_is_positive` attribute must not have its discharge subtracted
    from a production-positive aggregate.
    """
    region, street, house, street_total, *_ = setup_nested_groups

    battery_asset = GenericAsset(
        name="House battery",
        generic_asset_type=street.generic_asset_type,
        parent_asset=house,
    )
    db.session.add(battery_asset)
    temp_assets.append(battery_asset)
    db.session.flush()
    discharge = Sensor(
        "battery power",
        generic_asset=battery_asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="UTC",
    )
    db.session.add(discharge)
    db.session.flush()
    assert "consumption_is_positive" not in (discharge.attributes or {})
    battery_asset.flex_model = {
        "sensor": discharge.id,
        "group": {"asset": house.id},
        "power-capacity": "100 kW",
    }
    source = db.session.execute(
        db.select(DataSource).filter_by(name="nested meter")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 7, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=50,
                sensor=discharge,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": street.id}})
    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # 0.12 plus 50 kW read as production, not minus it
    assert result["event_value"].values == pytest.approx(0.17)


def test_member_source_filters_are_inherited(
    setup_nested_groups, db, restore_flex_models
):
    """The provenance a member's flex-config states is used for the belief search, not restated in the report."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    restore_flex_models(far_power.generic_asset)
    # the data is recorded by a source of type "A", so a filter for forecasters silences this member
    far_power.generic_asset.flex_model = {
        "inflexible-production": {
            "sensor": far_power.id,
            "source-types": ["forecaster"],
        },
        "group": {"asset": street.id},
    }
    db.session.commit()

    reporter = AggregatorReporter(
        config={"group": {"asset": street.id}, "skip-missing": True}
    )
    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # the far PV contributes nothing now: 100 kW of PV minus 40 kW of heat pump
    assert result["event_value"].values == pytest.approx(0.06)


def _at(result, event_start):
    return result[
        result.index.get_level_values("event_start") == pd.Timestamp(event_start)
    ]


def test_a_gap_in_one_member_is_recorded_under_a_source_naming_it(
    setup_nested_groups, db, restore_beliefs
):
    """A member with no data for an event leaves a partial aggregate, which says which member it is missing.

    The partial aggregate is not counted as complete, and it does not quietly lower a complete one:
    it is recorded under a source of its own, and the complete events keep the source a complete report always had.
    """
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    # remove one event from the heat pump's data
    missing_start = datetime(2026, 7, 1, 10, 0, tzinfo=utc)
    restore_beliefs(hp_power, missing_start)

    reporter = AggregatorReporter(config={"group": {"asset": street.id}})
    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    at_gap = _at(result, missing_start)
    # without the heat pump's 40 kW, only the PV is left
    assert at_gap["event_value"].values == pytest.approx(0.16)
    partial_source = at_gap.index.get_level_values("source")[0]
    assert partial_source.missing_members == [hp_power.id]
    assert partial_source.attributes["data_generator"]["config"][
        "resolved-members"
    ] == sorted([pv_power.id, hp_power.id, far_power.id])

    complete = result[
        result.index.get_level_values("event_start") != pd.Timestamp(missing_start)
    ]
    assert set(complete.index.get_level_values("source")) == {reporter.data_source}
    assert "missing-members" not in (
        reporter.data_source.attributes["data_generator"]["config"]
    )
    assert partial_source != reporter.data_source

    # asked to, a group report leaves such an event out instead
    strict = AggregatorReporter(
        config={"group": {"asset": street.id}, "skip-missing": False}
    ).compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[
        0
    ][
        "data"
    ]
    assert pd.isna(_at(strict, missing_start)["event_value"]).all()


def test_each_set_of_missing_members_has_a_source_of_its_own(
    setup_nested_groups, db, restore_beliefs
):
    """Which members are missing can differ per event, and a set that is missing again is recorded under the same source."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    hp_missing = datetime(2026, 7, 1, 10, 0, tzinfo=utc)
    far_missing = datetime(2026, 7, 1, 11, 0, tzinfo=utc)
    both_missing = datetime(2026, 7, 1, 12, 0, tzinfo=utc)
    restore_beliefs(hp_power, hp_missing)
    restore_beliefs(far_power, far_missing)
    restore_beliefs(hp_power, both_missing)
    restore_beliefs(far_power, both_missing)

    def sources_at_the_gaps():
        result = AggregatorReporter(config={"group": {"asset": street.id}}).compute(
            start=datetime(2026, 7, 1, tzinfo=utc),
            end=datetime(2026, 7, 2, tzinfo=utc),
            belief_horizon=timedelta(0),
        )[0]["data"]
        return [
            _at(result, event_start).index.get_level_values("source")[0]
            for event_start in (hp_missing, far_missing, both_missing)
        ]

    first = sources_at_the_gaps()
    assert [source.missing_members for source in first] == [
        [hp_power.id],
        [far_power.id],
        sorted([hp_power.id, far_power.id]),
    ]
    assert len({source.id for source in first}) == 3

    again = sources_at_the_gaps()
    assert [source.id for source in again] == [source.id for source in first]


def test_a_partial_aggregate_gets_a_source_of_its_own_also_when_the_config_is_not_saved(
    setup_nested_groups, db, restore_beliefs
):
    """Which members an aggregate covers, and which it leaves out, says what its data is, so it is recorded also where the config is not saved, as on the CLI by default."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    missing_start = datetime(2026, 7, 1, 10, 0, tzinfo=utc)
    restore_beliefs(hp_power, missing_start)

    reporter = AggregatorReporter(
        config={"group": {"asset": street.id}}, save_config=False
    )
    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    members = sorted([pv_power.id, hp_power.id, far_power.id])
    partial_source = _at(result, missing_start).index.get_level_values("source")[0]
    assert partial_source.missing_members == [hp_power.id]
    assert partial_source != reporter.data_source
    assert reporter.data_source.missing_members == []
    # the rest of the config is still not saved
    assert reporter.data_source.attributes["data_generator"] == {
        "config": {"resolved-members": members}
    }
    assert partial_source.attributes["data_generator"] == {
        "config": {"resolved-members": members, "missing-members": [hp_power.id]}
    }


def test_a_gap_in_a_sensor_named_besides_the_group_is_no_missing_member(
    setup_nested_groups, db, restore_beliefs
):
    """A sensor named in `input` next to the group is not one of its members, so a gap in it leaves the group's aggregate complete."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    missing_start = datetime(2026, 7, 1, 10, 0, tzinfo=utc)
    restore_beliefs(far_power, missing_start)

    reporter = AggregatorReporter(config={"group": {"asset": house.id}})
    result = reporter.compute(
        input=[dict(sensor=far_power)],
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    assert set(result.index.get_level_values("source")) == {reporter.data_source}
    # the house consumes 40 kW and produces 100 kW, and the far PV's 60 kW is what is missing
    assert _at(result, missing_start)["event_value"].values == pytest.approx(-0.06)


@pytest.mark.parametrize("kind", ["group", "input"])
def test_missing_members_given_in_the_config_are_overwritten(
    setup_nested_groups, db, kind
):
    """Which members were missing is the reporter's finding, so a complete report records none, whatever it was given.

    That holds for a report over sensors named in `input` too, which never records missing members.
    """
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    if kind == "group":
        config = {"group": {"asset": street.id}}
        parameters = {}
    else:
        config = {"method": "sum"}
        parameters = dict(
            input=[dict(sensor=pv_power), dict(sensor=hp_power)],
            output=[dict(sensor=street_total)],
        )
    reporter = AggregatorReporter(config={**config, "missing-members": [pv_power.id]})
    result = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
        **parameters,
    )[0]["data"]

    assert set(result.index.get_level_values("source")) == {reporter.data_source}
    assert reporter.data_source.missing_members == []


def test_a_complete_aggregate_computed_again_supersedes_a_partial_one_recorded_since(
    setup_nested_groups, db, restore_beliefs
):
    """A complete aggregate that says what the complete source said before is still saved where a partial one was recorded since.

    Otherwise the partial aggregate would remain the most recent belief about the event, which every consumer of one belief per event reads.
    The other events, whose complete aggregate did not change, are still not saved again.
    """
    from flexmeasures.data.services.generator_results import save_generator_results

    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    aggregate = Sensor(
        "street supersede test",
        generic_asset=street,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        timezone="UTC",
    )
    db.session.add(aggregate)
    db.session.commit()
    gap = datetime(2026, 7, 1, 10, 0, tzinfo=utc)

    def report(belief_time) -> int:
        results = AggregatorReporter(config={"group": {"asset": street.id}}).compute(
            output=[dict(sensor=aggregate)],
            start=datetime(2026, 7, 1, tzinfo=utc),
            end=datetime(2026, 7, 2, tzinfo=utc),
            belief_time=belief_time,
        )
        saved = save_generator_results(results)
        db.session.commit()
        return saved[0]["n_rows"]

    def read_at_gap():
        bdf = TimedBelief.search(
            aggregate,
            event_starts_after=gap,
            event_ends_before=gap + timedelta(minutes=15),
            one_deterministic_belief_per_event=True,
        )
        return bdf["event_value"].iloc[0], bdf.sources[0]

    back = None
    try:
        assert report(datetime(2026, 7, 2, 0, tzinfo=utc)) == 96
        # the heat pump's reading of one event is gone, so the next run records a partial aggregate of it
        restore_beliefs(hp_power, gap)
        assert report(datetime(2026, 7, 2, 1, tzinfo=utc)) == 1
        value, source = read_at_gap()
        assert value == pytest.approx(0.16)
        assert source.missing_members == [hp_power.id]

        # the reading is uploaded again, and the next run computes the same complete aggregate as the first
        meter = db.session.execute(
            db.select(DataSource).filter_by(name="nested meter")
        ).scalar_one()
        back = TimedBelief(
            event_start=gap,
            belief_time=datetime(2026, 7, 2, 1, 30, tzinfo=utc),
            event_value=40,
            sensor=hp_power,
            source=meter,
        )
        db.session.add(back)
        db.session.commit()
        assert report(datetime(2026, 7, 2, 2, tzinfo=utc)) == 1
        value, source = read_at_gap()
        assert value == pytest.approx(0.12)
        assert source.missing_members == []
        # running the same report again saves nothing
        assert report(datetime(2026, 7, 2, 2, tzinfo=utc)) == 0
    finally:
        if back is not None:
            db.session.delete(back)
        db.session.execute(db.delete(TimedBelief).filter_by(sensor_id=aggregate.id))
        db.session.delete(aggregate)
        db.session.commit()


def test_the_status_of_a_partial_aggregate_names_the_missing_members(
    setup_nested_groups, db, restore_beliefs
):
    """A partial aggregate says something about the current state of the group, so its status says which members it leaves out.

    Only an aggregate as old as the sensor's maximum staleness is judged, since a newer one may still be completed by the next run.
    Once the aggregate is recorded complete, the status no longer names them.
    """
    from flexmeasures.data.services.sensors import get_statuses

    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    aggregate = Sensor(
        "street status test",
        generic_asset=street,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        timezone="UTC",
    )
    db.session.add(aggregate)
    db.session.commit()
    status_specs = {
        "staleness_search": {},
        "max_staleness": "PT2H",
        "max_future_staleness": "-PT12H",
    }
    now = datetime(2026, 7, 2, 2, tzinfo=utc)
    last_event = datetime(2026, 7, 1, 23, 45, tzinfo=utc)

    def report(belief_time):
        result = AggregatorReporter(config={"group": {"asset": street.id}}).compute(
            output=[dict(sensor=aggregate)],
            start=datetime(2026, 7, 1, tzinfo=utc),
            end=datetime(2026, 7, 2, tzinfo=utc),
            belief_time=belief_time,
        )[0]["data"]
        save_to_db(result, save_changed_beliefs_only=False)
        db.session.commit()

    def reporter_status(now=now):
        statuses = get_statuses(aggregate, now=now, status_specs=status_specs)
        return next(
            status for status in statuses if status["source_type"] == "reporter"
        )

    late = None
    try:
        restore_beliefs(hp_power, last_event)
        report(datetime(2026, 7, 2, tzinfo=utc))
        # half an hour after the event, the next run may still complete it
        assert (
            reporter_status(datetime(2026, 7, 2, 0, 30, tzinfo=utc))["missing_members"]
            == []
        )
        status = reporter_status()
        assert status["missing_members"] == [dict(id=hp_power.id, name=hp_power.name)]
        assert f"leaves out 'hp power' ({hp_power.id})" in status["reason"]
        assert status["stale"] is False

        # the heat pump's data arrives, and a later run records the complete aggregate
        source = db.session.execute(
            db.select(DataSource).filter_by(name="nested meter")
        ).scalar_one()
        late = TimedBelief(
            event_start=last_event,
            belief_horizon=-timedelta(minutes=30),
            event_value=40,
            sensor=hp_power,
            source=source,
        )
        db.session.add(late)
        db.session.commit()
        report(datetime(2026, 7, 2, 1, tzinfo=utc))
        status = reporter_status()
        assert status["missing_members"] == []
        assert "leaves out" not in status["reason"]
    finally:
        if late is not None:
            db.session.delete(late)
        db.session.execute(db.delete(TimedBelief).filter_by(sensor_id=aggregate.id))
        db.session.delete(aggregate)
        db.session.commit()


def test_the_status_goes_by_the_aggregate_a_consumer_picks(setup_nested_groups, db):
    """Where a partial and a complete aggregate of the latest event share a belief time, the status names no missing members, as every consumer reads the complete one.

    The partial source is the older one here, so that its belief is not merely the last one in any order by source id.
    """
    from flexmeasures.data.services.sensors import get_statuses

    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    aggregate = Sensor(
        "street tie test",
        generic_asset=street,
        event_resolution=timedelta(minutes=15),
        unit="MW",
        timezone="UTC",
    )
    family = dict(
        name="Seita", type="reporter", model="AggregatorReporter", version="2"
    )
    partial = DataSource(
        **family,
        attributes={"data_generator": {"config": {"missing-members": [hp_power.id]}}},
    )
    db.session.add_all([aggregate, partial])
    db.session.flush()
    complete = DataSource(
        **family, attributes={"data_generator": {"config": {"resolved-members": []}}}
    )
    db.session.add(complete)
    db.session.flush()
    last_event = datetime(2026, 7, 1, 23, 45, tzinfo=utc)
    db.session.add_all(
        [
            TimedBelief(
                event_start=last_event,
                belief_time=datetime(2026, 7, 2, tzinfo=utc),
                event_value=value,
                sensor=aggregate,
                source=source,
            )
            for source, value in ((partial, 0.16), (complete, 0.12))
        ]
    )
    db.session.commit()
    try:
        statuses = get_statuses(
            aggregate,
            now=datetime(2026, 7, 2, 2, tzinfo=utc),
            status_specs={
                "staleness_search": {},
                "max_staleness": "PT2H",
                "max_future_staleness": "-PT12H",
            },
        )
        status = next(
            status for status in statuses if status["source_type"] == "reporter"
        )
        assert status["missing_members"] == []
    finally:
        db.session.execute(db.delete(TimedBelief).filter_by(sensor_id=aggregate.id))
        db.session.delete(aggregate)
        db.session.delete(partial)
        db.session.delete(complete)
        db.session.commit()


def test_upsampling_does_not_fill_across_a_gap(setup_pv_group, db, restore_beliefs):
    """Carrying an hourly value across its own hour is right; carrying it across a missing hour is not."""
    _, pv_group, aggregate_sensor, _, carport_power, _, _, _ = setup_pv_group

    missing = datetime(2026, 6, 1, 5, 0, tzinfo=utc)
    restore_beliefs(carport_power, missing)

    result = AggregatorReporter(config={"method": "sum"}).compute(
        input=[dict(sensor=carport_power)],
        output=[dict(sensor=aggregate_sensor)],
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    starts = result.index.get_level_values("event_start")
    in_gap = result[
        (starts >= pd.Timestamp(missing))
        & (starts < pd.Timestamp(missing) + pd.Timedelta("1h"))
    ]
    assert len(in_gap) == 4
    assert pd.isna(in_gap["event_value"]).all()


def test_a_missing_hour_of_energy_is_not_reported_as_zero(
    setup_pv_group, db, temp_assets, restore_beliefs
):
    """An hour with no energy readings is missing, not an hour in which no energy flowed."""
    _, pv_group, _, _, _, _, _, _ = setup_pv_group

    meter_asset = GenericAsset(
        name="Gappy meter",
        generic_asset_type=pv_group.generic_asset_type,
        parent_asset=pv_group,
    )
    db.session.add(meter_asset)
    temp_assets.append(meter_asset)
    db.session.flush()
    quarter_hourly = Sensor(
        "energy",
        generic_asset=meter_asset,
        event_resolution=timedelta(minutes=15),
        unit="kWh",
        timezone="UTC",
    )
    hourly = Sensor(
        "hourly energy",
        generic_asset=meter_asset,
        event_resolution=timedelta(hours=1),
        unit="kWh",
        timezone="UTC",
    )
    db.session.add_all([quarter_hourly, hourly])
    db.session.flush()
    source = db.session.execute(
        db.select(DataSource).filter_by(name="pv measurements")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 6, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=1,
                sensor=quarter_hourly,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    # drop the whole 03:00 hour, so that its bin has nothing to sum
    gap_hour = datetime(2026, 6, 1, 3, 0, tzinfo=utc)
    for quarter in range(4):
        restore_beliefs(quarter_hourly, gap_hour + quarter * timedelta(minutes=15))

    result = AggregatorReporter(config={"method": "sum"}).compute(
        input=[dict(sensor=quarter_hourly)],
        output=[dict(sensor=hourly)],
        start=datetime(2026, 6, 1, tzinfo=utc),
        end=datetime(2026, 6, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    starts = result.index.get_level_values("event_start")
    at_gap = result[starts == pd.Timestamp(gap_hour)]
    assert len(at_gap) == 1
    assert pd.isna(at_gap["event_value"]).all()
    # the hours around it still add their four quarter-hours up
    assert result[starts == pd.Timestamp(gap_hour) - pd.Timedelta("1h")][
        "event_value"
    ].values == pytest.approx(4)


def test_resolved_membership_is_recorded_on_the_data_source(
    setup_nested_groups, db, temp_assets
):
    """A report records which sensors it aggregated, so adding a device records the next report differently.

    That the membership changed is noted in the group's audit log when the device is added, not by the report.
    """
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    reporter = AggregatorReporter(config={"group": {"asset": street.id}})
    first = reporter.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )
    save_to_db(first[0]["data"])
    db.session.commit()
    first_source = reporter.data_source
    recorded = first_source.attributes["data_generator"]["config"]["resolved-members"]
    assert sorted(recorded) == sorted([pv_power.id, hp_power.id, far_power.id])

    # add a PV to the house; nothing about the report changes
    extra = GenericAsset(
        name="Extra house PV",
        generic_asset_type=pv_power.generic_asset.generic_asset_type,
        parent_asset=house,
    )
    db.session.add(extra)
    temp_assets.append(extra)
    db.session.flush()
    extra_power = Sensor(
        "extra pv power",
        generic_asset=extra,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="UTC",
    )
    db.session.add(extra_power)
    db.session.flush()
    extra.flex_model = {
        "inflexible-production": {"sensor": extra_power.id},
        "group": {"asset": house.id},
    }
    source = db.session.execute(
        db.select(DataSource).filter_by(name="nested meter")
    ).scalar_one()
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 7, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=30,
                sensor=extra_power,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    later = AggregatorReporter(config={"group": {"asset": street.id}})
    later.compute(
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(hours=1),
    )
    second_source = later.data_source

    assert (
        extra_power.id
        in second_source.attributes["data_generator"]["config"]["resolved-members"]
    )
    # the membership is part of the source's identity, so this is a different source
    assert second_source.id != first_source.id


def test_an_input_cleans_the_readings_it_asks_for(setup_dummy_data, db):
    """An input entry may bound the readings it reads, the way a forecaster's regressors and a scheduler's references can.

    Sensor 1 records 1 and sensor 2 records -1, so their sum is 0.
    Holding the second at or above zero makes the same report add 1 and 0.
    """
    s1, s2, _, _, report_sensor, _ = setup_dummy_data
    source_1 = db.session.get(DataSource, 1)
    source_2 = db.session.get(DataSource, 2)

    def summed(second_input: dict):
        return AggregatorReporter(method="sum").compute(
            input=[dict(sensor=s1, source=source_1), second_input],
            output=[dict(sensor=report_sensor)],
            start=datetime(2023, 5, 10, tzinfo=utc),
            end=datetime(2023, 5, 11, tzinfo=utc),
        )[0]["data"]

    unbounded = summed(dict(sensor=s2, source=source_2))
    # Sensor 2 records no unit, so a bare number says what its own readings are bounded by.
    bounded = summed(dict(sensor=s2, source=source_2, lower=0))

    assert (unbounded == 0).all().event_value
    assert (bounded == 1).all().event_value


def test_an_input_snaps_the_readings_it_asks_for(setup_dummy_data, db):
    """Snapping runs before clipping here too, so a reading inside an interval is replaced by its target."""
    s1, _, _, _, report_sensor, _ = setup_dummy_data
    source_1 = db.session.get(DataSource, 1)

    result = AggregatorReporter(method="sum").compute(
        input=[
            dict(
                sensor=s1,
                source=source_1,
                snap={"1.5 kW": ["0.5 kW", "1.5 kW"]},
            )
        ],
        output=[dict(sensor=report_sensor)],
        start=datetime(2023, 5, 10, tzinfo=utc),
        end=datetime(2023, 5, 11, tzinfo=utc),
    )[0]["data"]

    # Sensor 1 records 1 kW, which the interval [0.5, 1.5) covers, so it reads as its target.
    assert (result == 1.5).all().event_value


def test_a_bound_an_input_sensor_cannot_take_is_refused(setup_dummy_data, db):
    """A bound is checked against the sensor it applies to while the report is being set up, not once its data is read."""
    _, s2, _, _, report_sensor, _ = setup_dummy_data
    source_2 = db.session.get(DataSource, 2)

    with pytest.raises(ValidationError) as refusal:
        AggregatorReporter(method="sum").compute(
            # Sensor 2 records no unit, so a bound in kW cannot be read in it.
            input=[dict(sensor=s2, source=source_2, lower="0 kW")],
            output=[dict(sensor=report_sensor)],
            start=datetime(2023, 5, 10, tzinfo=utc),
            end=datetime(2023, 5, 11, tzinfo=utc),
        )

    assert "lower" in str(refusal.value)
    assert "sensor 2" in str(refusal.value)


def test_an_input_report_still_aggregates_what_reported(
    setup_nested_groups, db, restore_beliefs
):
    """A report over sensors the caller named keeps aggregating what reported, under its one source, as such reports always have.

    Only a report whose members were resolved for it records a partial aggregate under a source naming the missing members:
    there the caller cannot see which sensors went in, so a partial aggregate that looks complete is the worse failure.
    """
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    missing_start = datetime(2026, 7, 1, 11, 0, tzinfo=utc)
    restore_beliefs(hp_power, missing_start)

    reporter = AggregatorReporter(config={"method": "sum"})
    result = reporter.compute(
        input=[dict(sensor=pv_power), dict(sensor=hp_power)],
        output=[dict(sensor=street_total)],
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    at_gap = _at(result, missing_start)
    # the PV alone, in MW: 100 kW
    assert at_gap["event_value"].values == pytest.approx(0.1)
    assert set(result.index.get_level_values("source")) == {reporter.data_source}

    # and a group report over the same two sensors says which one it is missing
    group_result = AggregatorReporter(config={"group": {"asset": house.id}}).compute(
        output=[dict(sensor=street_total)],
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]
    group_at_gap = _at(group_result, missing_start)
    # the house records its consumption, so its PV counts negatively
    assert group_at_gap["event_value"].values == pytest.approx(-0.1)
    assert group_at_gap.index.get_level_values("source")[0].missing_members == [
        hp_power.id
    ]


def test_more_than_one_belief_about_an_event_is_refused(setup_nested_groups, db):
    """An input that asks for more than the most recent belief about each event is told which event it holds several beliefs about."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )
    source = db.session.execute(
        db.select(DataSource).filter_by(name="nested meter")
    ).scalar_one()
    earlier = TimedBelief(
        event_start=datetime(2026, 7, 1, 10, tzinfo=utc),
        belief_horizon=timedelta(hours=1),
        event_value=1,
        sensor=pv_power,
        source=source,
    )
    db.session.add(earlier)
    db.session.commit()
    try:
        with pytest.raises(ValueError, match="more than one belief about 1 event") as e:
            AggregatorReporter(config={"method": "sum"}).compute(
                input=[dict(sensor=pv_power, most_recent_beliefs_only=False)],
                output=[dict(sensor=street_total)],
                start=datetime(2026, 7, 1, tzinfo=utc),
                end=datetime(2026, 7, 2, tzinfo=utc),
                belief_time=datetime(2026, 7, 3, tzinfo=utc),
            )
        assert "2026-07-01 10:00:00+00:00" in str(e.value)
    finally:
        db.session.delete(earlier)
        db.session.commit()


def test_an_invalid_flex_model_on_the_site_names_the_asset(
    setup_nested_groups, db, restore_flex_models
):
    """A report fails on a flex-config a scheduler would fail on too, and says which asset's entry is at fault."""
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    # a device outside the group, with a capacity that is not a quantity
    restore_flex_models(far_power.generic_asset)
    far_power.generic_asset.flex_model = {
        "sensor": far_power.id,
        "power-capacity": "not a power",
    }
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": house.id}})
    with pytest.raises(ValueError) as error:
        reporter.compute(
            start=datetime(2026, 7, 1, tzinfo=utc),
            end=datetime(2026, 7, 2, tzinfo=utc),
            belief_horizon=timedelta(0),
        )

    message = str(error.value)
    assert "flex-config of site" in message
    assert f"{far_power.generic_asset.id} ({far_power.generic_asset.name})" in message


def test_a_device_with_a_power_sensor_is_read_from_it(
    setup_nested_groups, db, temp_assets
):
    """A device that has its own power sensor is read from that sensor, not from where its schedule is written.

    A battery may name a power sensor holding its measurements and, separately, `consumption` and `production`
    sensors the scheduler writes to. Reading the latter would find nothing for a realized report,
    and with the every-member-must-report rule the whole aggregate would come out empty.
    """
    region, street, house, street_total, *_ = setup_nested_groups

    battery = GenericAsset(
        name="Split battery",
        generic_asset_type=street.generic_asset_type,
        parent_asset=house,
    )
    db.session.add(battery)
    temp_assets.append(battery)
    db.session.flush()

    def sensor(name):
        s = Sensor(
            name,
            generic_asset=battery,
            event_resolution=timedelta(minutes=15),
            unit="kW",
            timezone="UTC",
        )
        db.session.add(s)
        return s

    measured = sensor("battery power")
    scheduled_consumption = sensor("battery consumption")
    scheduled_production = sensor("battery production")
    db.session.flush()
    battery.flex_model = {
        "sensor": measured.id,
        "consumption": {"sensor": scheduled_consumption.id},
        "production": {"sensor": scheduled_production.id},
        "group": {"asset": house.id},
        "power-capacity": "100 kW",
    }
    source = db.session.execute(
        db.select(DataSource).filter_by(name="nested meter")
    ).scalar_one()
    # only the power sensor holds measurements; the two output sensors are empty
    db.session.add_all(
        [
            TimedBelief(
                event_start=datetime(2026, 7, 1, tzinfo=utc)
                + event * timedelta(minutes=15),
                belief_horizon=timedelta(0),
                event_value=20,
                sensor=measured,
                source=source,
            )
            for event in range(96)
        ]
    )
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": house.id}})
    read = [s.id for s in reporter.input_sensors]
    assert measured.id in read
    assert scheduled_consumption.id not in read
    assert scheduled_production.id not in read

    result = reporter.compute(
        output=[dict(sensor=street_total)],
        start=datetime(2026, 7, 1, tzinfo=utc),
        end=datetime(2026, 7, 2, tzinfo=utc),
        belief_horizon=timedelta(0),
    )[0]["data"]

    # The house records its aggregate under `consumption`, so this aggregate is consumption-positive:
    # the heat pump's 40 kW counts positive, while the PV's 100 kW and the battery's 20 kW are production
    # and count negative. 40 - 100 - 20 = -80 kW.
    assert result["event_value"].values == pytest.approx(-0.08)


def test_an_invalid_flex_model_names_only_the_faulty_asset(
    setup_nested_groups, db, restore_flex_models
):
    """The asset at fault is named, and not every ancestor that fails along with it.

    A scheduler on an asset reads its subtree too, so probing the street and the house both fail
    when the fault is on a device below them.
    """
    region, street, house, street_total, house_total, pv_power, hp_power, far_power = (
        setup_nested_groups
    )

    restore_flex_models(pv_power.generic_asset)
    pv_power.generic_asset.flex_model = {
        "inflexible-production": {"sensor": pv_power.id},
        "group": {"asset": house.id},
        "power-capacity": "not a power",
    }
    db.session.commit()

    reporter = AggregatorReporter(config={"group": {"asset": house.id}})
    with pytest.raises(ValueError) as error:
        reporter.compute(
            start=datetime(2026, 7, 1, tzinfo=utc),
            end=datetime(2026, 7, 2, tzinfo=utc),
            belief_horizon=timedelta(0),
        )

    message = str(error.value)
    assert f"{pv_power.generic_asset.id} ({pv_power.generic_asset.name})" in message
    # the street and the house fail only because the fault sits below them
    assert f"{street.id} ({street.name})" not in message
    assert f"{house.id} ({house.name})" not in message
