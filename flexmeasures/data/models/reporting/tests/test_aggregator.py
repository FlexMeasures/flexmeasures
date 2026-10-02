import pytest
from marshmallow import ValidationError

from flexmeasures.data.models.reporting.aggregator import AggregatorReporter
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
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


def test_group_leaves_out_its_own_aggregate_sensor(setup_pv_group, db):
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

    db.session.delete(double_counter)
    db.session.commit()


def test_group_membership_is_what_drives_the_report(setup_pv_group, db):
    """Only the entries that declare the group are aggregated, which is what makes the flex-config the source of truth."""
    _, pv_group, _, roof_power, carport_power, _, roof, _ = setup_pv_group

    reporter = AggregatorReporter(config={"group": {"asset": pv_group.id}})
    assert sorted(s.id for s in reporter.input_sensors) == sorted(
        [roof_power.id, carport_power.id]
    )

    # take the roof out of the group, and the report follows
    kept = roof.flex_model
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

    roof.flex_model = kept
    db.session.commit()


def test_energy_output_sums_over_a_longer_event(setup_pv_group, db):
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

    db.session.delete(meter_asset)
    db.session.commit()


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


def test_group_adding_a_member_needs_no_report_change(setup_pv_group, db):
    """Adding a PV installation to the group adds it to the report, with nothing to keep in sync."""
    farm, pv_group, aggregate_sensor, _, _, _, _, _ = setup_pv_group

    extra_asset = GenericAsset(
        name="Shed PV",
        generic_asset_type=pv_group.generic_asset_type,
        parent_asset=pv_group,
    )
    db.session.add(extra_asset)
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

    db.session.delete(extra_asset)
    db.session.commit()


def test_group_refuses_an_incomparable_member(setup_pv_group, db):
    """A member recording something other than power cannot be added to a power aggregate."""
    _, pv_group, _, _, _, temperature, _, _ = setup_pv_group

    weather_asset = temperature.generic_asset
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

    weather_asset.flex_model = {}
    db.session.commit()


def test_group_without_an_aggregate_sensor(setup_pv_group, db):
    """A group whose entry says nowhere to record the aggregate is reported as such."""
    _, pv_group, aggregate_sensor, _, _, _, _, _ = setup_pv_group

    kept = pv_group.flex_model
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

    pv_group.flex_model = kept
    db.session.commit()


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


def test_energy_sensor_converted_at_its_own_resolution(setup_pv_group, db):
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

    db.session.delete(energy_asset)
    db.session.commit()
