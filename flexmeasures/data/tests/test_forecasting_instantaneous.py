"""Tests for taking an instantaneous sensor's beliefs onto the slots of a forecast, under step-before (ffill) interpolation."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from flexmeasures.data.models.forecasting.pipelines.instantaneous import (
    INFER_LIMIT,
    InterpolationAttributeError,
    interpolation_policy,
    sample_instantaneous_beliefs,
)

HOUR = timedelta(hours=1)
ANCHOR = pd.Timestamp("2025-01-15T00:00", tz="UTC")
END = pd.Timestamp("2025-01-15T16:00", tz="UTC")


class _Thermometer:
    """A stand-in for an instantaneous sensor with the default (ex-post) knowledge horizon."""

    id = 1

    def __init__(self, **attributes):
        self.attributes = attributes

    def get_attribute(self, name, default=None):
        return self.attributes.get(name, default)

    def knowledge_time(self, event_starts, event_resolution):
        # Ex-post: an event is known once it has ended.
        return event_starts + event_resolution


MEASURER, FORECASTER = "measurer", "forecaster"


def _t(hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"2025-01-15T{hhmm}", tz="UTC")


def _beliefs(*rows) -> pd.DataFrame:
    """Rows of (event start, belief time, value, source); beliefs recorded at or after their instant are measurements."""
    df = pd.DataFrame(
        rows, columns=["event_start", "belief_time", "event_value", "source"]
    )
    df["event_start"] = df["event_start"].map(_t)
    df["belief_time"] = df["belief_time"].map(_t)
    df["is_realized"] = df["belief_time"] >= df["event_start"]
    return df


READINGS = _beliefs(
    ("09:52", "09:52", 3.9, MEASURER),
    ("10:07", "10:07", 4.1, MEASURER),
    ("10:37", "10:37", 6.0, MEASURER),
    ("13:10", "13:10", 5.0, MEASURER),
)


def _sample(beliefs, period=False, **kwargs):
    kwargs.setdefault("limit", None)
    out = sample_instantaneous_beliefs(
        beliefs, _Thermometer(), HOUR, ANCHOR, END, period=period, **kwargs
    )
    return out.set_index("event_start")


def test_a_reading_holds_until_the_next_one():
    """Each instant takes the last reading at or before it, which is only known once that instant has come."""
    out = _sample(READINGS)
    assert (
        out.loc[_t("10:00"), "event_value"] == 3.9
    )  # from 09:52, not the 10:07 reading after it
    assert (
        out.loc[_t("11:00"), "event_value"] == 6.0
    )  # the latest reading in the hour before
    assert out.loc[_t("12:00"), "event_value"] == 6.0  # held, as there is no limit
    assert out.loc[_t("14:00"), "event_value"] == 5.0
    assert (out["belief_time"] == out.index).all()
    assert out["is_realized"].all()


def test_readings_on_the_grid_stand_for_their_own_instant():
    """Hourly readings infer a limit of two hours, so the last one holds into the next instant, but not the one after."""
    readings = _beliefs(
        ("10:00", "10:00", 1.0, MEASURER), ("11:00", "11:00", 2.0, MEASURER)
    )
    out = _sample(readings, limit=INFER_LIMIT)
    assert out["event_value"].to_dict() == {
        _t("10:00"): 1.0,
        _t("11:00"): 2.0,
        _t("12:00"): 2.0,
    }


def test_a_value_holds_no_longer_than_the_limit():
    """With a 30-minute limit, 10:37 holds until 11:07, so noon has no value; neither has 14:00, as 13:10 holds until 13:40."""
    out = _sample(READINGS, limit=timedelta(minutes=30))
    assert out.loc[_t("10:00"), "event_value"] == 3.9
    assert out.loc[_t("11:00"), "event_value"] == 6.0
    assert _t("12:00") not in out.index
    assert _t("13:00") not in out.index
    assert _t("14:00") not in out.index


def test_without_a_limit_attribute_the_limit_is_twice_the_usual_gap():
    """Readings every 15 minutes hold for at most 30 minutes, so a reading at 10:15 does not reach 11:00 once the readings stop."""
    readings = _beliefs(
        *[
            (f"{h:02d}:{m:02d}", f"{h:02d}:{m:02d}", float(h), MEASURER)
            for h in (9, 10)
            for m in (0, 15)
        ]
    )
    out = _sample(readings, limit=INFER_LIMIT)
    assert out.loc[_t("10:00"), "event_value"] == 10.0
    assert _t("11:00") not in out.index


def test_the_none_policy_uses_only_readings_on_the_grid():
    out = _sample(READINGS, policy="none")
    assert out.empty
    on_grid = _beliefs(
        ("10:00", "10:00", 1.0, MEASURER), ("10:30", "10:30", 2.0, MEASURER)
    )
    out = _sample(on_grid, policy="none")
    assert out["event_value"].to_dict() == {_t("10:00"): 1.0}


def test_a_held_measurement_is_known_from_its_instant_or_its_recording_whichever_is_later():
    """A reading at 10:07 that is only recorded at 11:30 stands for 11:00, but cannot be known before 11:30."""
    late = _beliefs(
        ("10:07", "11:30", 4.1, MEASURER), ("12:20", "12:20", 5.0, MEASURER)
    )
    out = _sample(late)
    assert out.loc[_t("11:00"), "belief_time"] == _t("11:30")
    assert out.loc[_t("12:00"), "belief_time"] == _t("12:00")
    assert out["is_realized"].all()


def test_a_correction_known_by_an_instant_is_the_value_held_into_it():
    """Both the reading and its correction are recorded before 11:00, so 11:00 holds the correction."""
    corrected = _beliefs(
        ("10:07", "10:07", 4.1, MEASURER), ("10:07", "10:50", 4.3, MEASURER)
    )
    out = _sample(corrected)
    assert out.loc[_t("11:00"), "event_value"] == 4.3


def test_a_held_forecast_keeps_its_belief_time_and_stays_a_forecast():
    """A forecast made at 08:00 for 10:15 and 10:45 holds within that forecast, and none of its rows is realized."""
    beliefs = _beliefs(
        ("10:15", "08:00", 5.0, FORECASTER),
        ("10:45", "08:00", 7.0, FORECASTER),
        (
            "12:00",
            "08:00",
            9.0,
            FORECASTER,
        ),  # a forecast for its own instant on the grid
    )
    out = _sample(beliefs)
    assert (
        out.loc[_t("11:00"), "event_value"] == 7.0
    )  # the forecast for 10:45 holds until the next event in the same forecast
    assert out.loc[_t("12:00"), "event_value"] == 9.0
    assert (out["belief_time"] == _t("08:00")).all()
    assert not out["is_realized"].any()


def test_forecasts_only_hold_within_their_own_forecast():
    """A later forecast does not end an earlier one's values, and each instant gets a row per forecast."""
    beliefs = _beliefs(
        ("10:15", "08:00", 5.0, FORECASTER),
        ("10:30", "09:00", 6.0, FORECASTER),
    )
    out = sample_instantaneous_beliefs(
        beliefs, _Thermometer(), HOUR, ANCHOR, _t("12:00"), period=False, limit=None
    )
    at_11 = out[out["event_start"] == _t("11:00")].set_index("belief_time")[
        "event_value"
    ]
    assert at_11.to_dict() == {_t("08:00"): 5.0, _t("09:00"): 6.0}


def test_a_period_takes_the_time_weighted_mean_of_the_held_values():
    """10:00-11:00 holds 3.9 for 7 minutes, 4.1 for 30 and 6.0 for 23; it is known once the period has ended."""
    out = _sample(READINGS, period=True)
    assert out.loc[_t("10:00"), "event_value"] == pytest.approx(
        (7 * 3.9 + 30 * 4.1 + 23 * 6.0) / 60
    )
    assert out.loc[_t("10:00"), "belief_time"] == _t("11:00")
    assert out.loc[_t("10:00"), "is_realized"]


def test_a_period_only_partly_covered_is_missing():
    """With a 30-minute limit, 10:37 holds until 11:07, which covers only part of 11:00-12:00."""
    out = _sample(READINGS, period=True, limit=timedelta(minutes=30))
    assert _t("10:00") in out.index
    assert _t("11:00") not in out.index


def test_a_forecast_period_mean_stays_within_one_forecast():
    beliefs = _beliefs(
        ("10:00", "08:00", 5.0, FORECASTER), ("10:30", "08:00", 7.0, FORECASTER)
    )
    out = sample_instantaneous_beliefs(
        beliefs, _Thermometer(), HOUR, ANCHOR, _t("11:00"), period=True, limit=None
    )
    out = out.set_index("event_start")
    assert out.loc[_t("10:00"), "event_value"] == pytest.approx(6.0)
    assert out.loc[_t("10:00"), "belief_time"] == _t("08:00")
    assert not out.loc[_t("10:00"), "is_realized"]


@pytest.mark.parametrize(
    ["attributes", "expected"],
    [
        ({}, ("ffill", INFER_LIMIT)),
        ({"interpolation": "none"}, ("none", INFER_LIMIT)),
        ({"interpolation_limit": None}, ("ffill", None)),
        ({"interpolation_limit": "PT2H"}, ("ffill", timedelta(hours=2))),
    ],
)
def test_interpolation_attributes(attributes, expected):
    assert interpolation_policy(_Thermometer(**attributes)) == expected


@pytest.mark.parametrize(
    "attributes",
    [
        {"interpolation": "linear"},
        {"interpolation_limit": "P1M"},
        {"interpolation_limit": "PT0H"},
        {"interpolation_limit": 3},
    ],
)
def test_unusable_interpolation_attributes_are_refused(attributes):
    with pytest.raises(InterpolationAttributeError, match="interpolation"):
        interpolation_policy(_Thermometer(**attributes))


# Database-backed helpers

NOW = pd.Timestamp("2025-01-15T12:23:58+01", tz="Europe/Amsterdam")
START = pd.Timestamp("2025-01-15T12:00+01", tz="Europe/Amsterdam")


@pytest.fixture
def thermometer_setup(fresh_db):
    """An asset and two data sources to record instantaneous readings with."""
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType

    asset_type = GenericAssetType(name="fridge type")
    asset = GenericAsset(name="fridge", generic_asset_type=asset_type)
    sources = [
        DataSource(name=name, type="demo script") for name in ("probe A", "probe B")
    ]
    fresh_db.session.add_all([asset_type, asset, *sources])
    fresh_db.session.flush()
    return asset, sources


def _thermometer(db, asset, **attributes):
    from flexmeasures.data.models.time_series import Sensor

    sensor = Sensor(
        "thermometer",
        generic_asset=asset,
        unit="°C",
        event_resolution=timedelta(0),
        attributes=attributes,
    )
    db.session.add(sensor)
    db.session.flush()
    return sensor


def _record(db, sensor, source, offsets, until=NOW):
    from flexmeasures.data.models.time_series import TimedBelief

    db.session.add_all(
        TimedBelief(
            sensor=sensor,
            source=source,
            event_start=until + offset,
            belief_time=until + offset,
            event_value=4.0,
        )
        for offset in offsets
    )
    db.session.flush()


# Leak tests: what an instantaneous regressor tells forecasts issued at different times


def _leak_setup(db, thermometer_setup):
    """An instantaneous target, and an instantaneous thermometer with measurements and one forecast.

    Measurements: 2.0 at 08:00 and 4.1 at 10:07, each recorded at its instant.
    Forecast, made at 09:30: 5.0 for 10:15 and 9.0 for 12:00.
    """
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.time_series import Sensor, TimedBelief

    asset, (probe, _) = thermometer_setup
    forecaster = DataSource(name="weather service", type="forecaster")
    target = Sensor(
        "fridge state", generic_asset=asset, unit="kW", event_resolution=timedelta(0)
    )
    thermometer = Sensor(
        "thermometer",
        generic_asset=asset,
        unit="°C",
        event_resolution=timedelta(0),
        attributes={"interpolation_limit": None},
    )
    db.session.add_all([forecaster, target, thermometer])
    db.session.flush()
    beliefs = [
        TimedBelief(
            sensor=target,
            source=probe,
            event_start=_t(f"{h:02d}:00"),
            belief_time=_t(f"{h:02d}:00"),
            event_value=float(h),
        )
        for h in range(6, 13)
    ]
    beliefs += [
        TimedBelief(
            sensor=thermometer,
            source=probe,
            event_start=_t("08:00"),
            belief_time=_t("08:00"),
            event_value=2.0,
        ),
        TimedBelief(
            sensor=thermometer,
            source=probe,
            event_start=_t("10:07"),
            belief_time=_t("10:07"),
            event_value=4.1,
        ),
        TimedBelief(
            sensor=thermometer,
            source=forecaster,
            event_start=_t("10:15"),
            belief_time=_t("09:30"),
            event_value=5.0,
        ),
        TimedBelief(
            sensor=thermometer,
            source=forecaster,
            event_start=_t("12:00"),
            belief_time=_t("09:30"),
            event_value=9.0,
        ),
    ]
    db.session.add_all(beliefs)
    db.session.flush()
    from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline

    pipeline = BasePipeline(
        target_sensor=target,
        future_regressors=[thermometer],
        past_regressors=[],
        n_steps_to_predict=4,
        max_forecast_horizon=3,
        forecast_frequency=1,
        event_starts_after=_t("06:00"),
        event_ends_before=_t("13:00"),
        predict_start=_t("09:00"),
        predict_end=_t("13:00"),
        resolution=HOUR,
    )
    return pipeline, thermometer


def test_measurements_and_forecasts_of_an_instantaneous_regressor_are_flagged_by_their_emitted_events(
    fresh_db, thermometer_setup
):
    """Held measurements are realized from their instant; a held forecast, and a forecast for its own instant, stay forecasts.

    Without an interpolation limit, the last values hold until the end of the data, which for a future regressor reaches the maximum horizon (16:00).
    """
    pipeline, _ = _leak_setup(fresh_db, thermometer_setup)
    df = pipeline.load_data_all_beliefs()
    name = pipeline.future_regressors[0]
    rows = df.dropna(subset=[name]).set_index(["event_start", "belief_time"])
    flags = rows[f"{name}__realized"]
    naive = lambda hhmm: _t(hhmm).tz_localize(None)  # noqa: E731
    forecast_rows = rows.xs(naive("09:30"), level="belief_time")
    assert forecast_rows[name].to_dict() == {
        naive("11:00"): 5.0,
        naive("12:00"): 9.0,
        naive("13:00"): 9.0,
        naive("14:00"): 9.0,
        naive("15:00"): 9.0,
    }
    assert not flags.xs(naive("09:30"), level="belief_time").any()
    measurement_rows = rows.drop(naive("09:30"), level="belief_time")
    assert measurement_rows[name].to_dict() == {
        (naive("08:00"), naive("08:00")): 2.0,
        (naive("09:00"), naive("09:00")): 2.0,
        (naive("10:00"), naive("10:00")): 2.0,
        (naive("11:00"), naive("11:00")): 4.1,
        (naive("12:00"), naive("12:00")): 4.1,
        (naive("13:00"), naive("13:00")): 4.1,
        (naive("14:00"), naive("14:00")): 4.1,
        (naive("15:00"), naive("15:00")): 4.1,
    }
    assert flags.drop(naive("09:30"), level="belief_time").all()


def test_an_instantaneous_regressor_tells_each_forecast_only_what_was_known_when_it_was_issued(
    fresh_db, thermometer_setup, monkeypatch
):
    """Per forecast issued at 09:00, 10:00, 11:00 and 12:00, the future values of the thermometer before gap filling.

    At 09:00, the state then (2.0) is known, but not the 10:07 reading, and not the forecast made at 09:30.
    At 10:00, the forecast is known, so it says 5.0 for 11:00 rather than the 10:07 reading held into 11:00, which is only known at 11:00.
    At 11:00, the held measurement is known, and supersedes the forecast for 11:00.
    """
    from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline

    pipeline, _ = _leak_setup(fresh_db, thermometer_setup)
    name = pipeline.future_regressors[0]
    captured = []

    def capture(self, df, sensors, sensor_names, start, end, **kwargs):
        if sensor_names[: len(self.future_regressors)] == self.future_regressors:
            captured.append(df.set_index("event_start")[name].dropna())
        return df

    monkeypatch.setattr(BasePipeline, "detect_and_fill_missing_values", capture)
    pipeline.split_data_all_beliefs(
        pipeline.load_data_all_beliefs(), is_predict_pipeline=True
    )
    naive = lambda hhmm: _t(hhmm).tz_localize(None)  # noqa: E731

    at_09, at_10, at_11, _ = captured
    assert at_09.to_dict() == {naive("08:00"): 2.0, naive("09:00"): 2.0}
    assert at_10.to_dict() == {
        naive("08:00"): 2.0,
        naive("09:00"): 2.0,
        naive("10:00"): 2.0,
        naive("11:00"): 5.0,
        naive("12:00"): 9.0,
        naive("13:00"): 9.0,
    }
    assert at_11[naive("11:00")] == 4.1
    assert at_11[naive("12:00")] == 9.0
