from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
import pytz
import timely_beliefs as tb

from flexmeasures.data.models.forecasting.model_spec_factory import (
    TBSeriesSpecs,
    configure_regressors_for_nearest_weather_sensor,
)


class _SensorWithWeatherCorrelations:
    def __init__(self, correlations: list[str]):
        self.name = "target-sensor"
        self._correlations = correlations

    def get_attribute(self, key: str):
        if key == "weather_correlations":
            return self._correlations
        return None


def _make_bdf() -> tb.BeliefsDataFrame:
    sensor = tb.Sensor(
        name="mock-regressor",
        unit="kW",
        timezone="UTC",
        event_resolution=timedelta(hours=1),
    )
    source = tb.BeliefSource(name="mock-source")
    belief = tb.TimedBelief(
        sensor=sensor,
        source=source,
        event_start=datetime(2025, 1, 1, tzinfo=pytz.utc),
        event_value=1.0,
        belief_horizon=timedelta(hours=1),
    )
    return tb.BeliefsDataFrame([belief])


def _make_bdf_with_source_duplicates() -> tb.BeliefsDataFrame:
    sensor = tb.Sensor(
        name="mock-regressor",
        unit="kW",
        timezone="UTC",
        event_resolution=timedelta(hours=1),
    )
    source_actual = tb.BeliefSource(name="flex.service")
    source_forecast = tb.BeliefSource(name="Thiink forecaster")

    # Historical event: prefer flex.service
    hist_event = datetime(2025, 1, 9, tzinfo=pytz.utc)
    # Future event: prefer Thiink forecaster
    fut_event = datetime(2025, 1, 11, tzinfo=pytz.utc)

    beliefs = [
        tb.TimedBelief(
            sensor=sensor,
            source=source_actual,
            event_start=hist_event,
            event_value=10.0,
            belief_time=datetime(2025, 1, 8, 12, tzinfo=pytz.utc),
        ),
        tb.TimedBelief(
            sensor=sensor,
            source=source_forecast,
            event_start=hist_event,
            event_value=11.0,
            belief_time=datetime(2025, 1, 8, 13, tzinfo=pytz.utc),
        ),
        tb.TimedBelief(
            sensor=sensor,
            source=source_actual,
            event_start=fut_event,
            event_value=20.0,
            belief_time=datetime(2025, 1, 10, 10, tzinfo=pytz.utc),
        ),
        tb.TimedBelief(
            sensor=sensor,
            source=source_forecast,
            event_start=fut_event,
            event_value=21.0,
            belief_time=datetime(2025, 1, 10, 11, tzinfo=pytz.utc),
        ),
    ]
    return tb.BeliefsDataFrame(beliefs)


def test_regressor_specs_include_issue_time_policy(monkeypatch):
    target_sensor = _SensorWithWeatherCorrelations(["irradiance"])
    closest_sensor = object()
    issue_time = pd.Timestamp("2025-01-10T00:00:00Z")
    query_window = (
        pd.Timestamp("2024-12-01T00:00:00Z"),
        pd.Timestamp("2025-01-20T00:00:00Z"),
    )

    monkeypatch.setattr(
        "flexmeasures.data.models.forecasting.model_spec_factory.Sensor.find_closest",
        lambda **_: closest_sensor,
    )
    monkeypatch.setattr(
        "flexmeasures.data.models.forecasting.model_spec_factory.current_app",
        SimpleNamespace(
            logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        ),
    )

    specs = configure_regressors_for_nearest_weather_sensor(
        sensor=target_sensor,
        query_window=query_window,
        horizon=timedelta(days=2),
        forecast_start=issue_time,
        regressor_transformation={},
        transform_to_normal=False,
    )

    assert len(specs) == 1
    search_params = specs[0].search_params
    assert search_params["sensors"] is closest_sensor
    assert search_params["policy_issue_time"] == issue_time
    assert search_params["horizons_at_least"] is None


def test_tb_series_specs_splits_regressor_queries_by_issue_time():
    class MockSearch:
        calls: list[dict] = []

        @classmethod
        def search(cls, **kwargs):
            cls.calls.append(kwargs)
            return _make_bdf()

    issue_time = pd.Timestamp("2025-01-10T00:00:00Z")
    spec = TBSeriesSpecs(
        name="irradiance_l0",
        time_series_class=MockSearch,
        search_params=dict(
            sensors=object(),
            event_starts_after=pd.Timestamp("2024-12-01T00:00:00Z"),
            event_ends_before=pd.Timestamp("2025-01-20T00:00:00Z"),
            horizons_at_least=None,
            horizons_at_most=None,
            policy_issue_time=issue_time,
        ),
    )

    series = spec._load_series()

    assert not series.empty
    assert len(MockSearch.calls) == 2

    historical_call, future_call = MockSearch.calls
    assert "policy_issue_time" not in historical_call
    assert "policy_future_horizon_floor" not in historical_call
    assert "policy_issue_time" not in future_call
    assert "policy_future_horizon_floor" not in future_call
    assert historical_call["horizons_at_least"] is None
    assert historical_call["event_ends_before"] == issue_time

    assert future_call["horizons_at_least"] is None
    assert future_call["event_starts_after"] == issue_time


def test_tb_series_specs_keeps_single_query_without_policy():
    class MockSearch:
        calls: list[dict] = []

        @classmethod
        def search(cls, **kwargs):
            cls.calls.append(kwargs)
            return _make_bdf()

    spec = TBSeriesSpecs(
        name="outcome",
        time_series_class=MockSearch,
        search_params=dict(
            sensors=object(),
            event_starts_after=pd.Timestamp("2024-12-01T00:00:00Z"),
            event_ends_before=pd.Timestamp("2025-01-20T00:00:00Z"),
            horizons_at_least=None,
            horizons_at_most=timedelta(hours=0),
        ),
    )

    series = spec._load_series()

    assert not series.empty
    assert len(MockSearch.calls) == 1


def test_tb_series_specs_accepts_issue_time_only_policy():
    class MockSearch:
        @classmethod
        def search(cls, **kwargs):
            return _make_bdf()

    spec = TBSeriesSpecs(
        name="irradiance_l0",
        time_series_class=MockSearch,
        search_params=dict(
            sensors=object(),
            event_starts_after=pd.Timestamp("2024-12-01T00:00:00Z"),
            event_ends_before=pd.Timestamp("2025-01-20T00:00:00Z"),
            horizons_at_least=None,
            horizons_at_most=None,
            policy_issue_time=pd.Timestamp("2025-01-10T00:00:00Z"),
        ),
    )

    series = spec._load_series()
    assert not series.empty


def test_tb_series_specs_skips_historical_query_for_future_only_window():
    class MockSearch:
        calls: list[dict] = []

        @classmethod
        def search(cls, **kwargs):
            cls.calls.append(kwargs)
            return _make_bdf()

    issue_time = pd.Timestamp("2025-01-10T00:00:00Z")
    spec = TBSeriesSpecs(
        name="irradiance_l0",
        time_series_class=MockSearch,
        search_params=dict(
            sensors=object(),
            event_starts_after=pd.Timestamp("2025-01-12T00:00:00Z"),
            event_ends_before=pd.Timestamp("2025-01-20T00:00:00Z"),
            horizons_at_least=None,
            horizons_at_most=None,
            policy_issue_time=issue_time,
        ),
    )

    spec._load_series()
    assert len(MockSearch.calls) == 1
    assert MockSearch.calls[0]["horizons_at_least"] is None


def test_tb_series_specs_source_preference_per_issue_time_bucket():
    class MockSearch:
        @classmethod
        def search(cls, **kwargs):
            return _make_bdf_with_source_duplicates()

    issue_time = pd.Timestamp("2025-01-10T00:00:00Z")
    spec = TBSeriesSpecs(
        name="irradiance_l0",
        time_series_class=MockSearch,
        search_params=dict(
            sensors=object(),
            event_starts_after=pd.Timestamp("2025-01-08T00:00:00Z"),
            event_ends_before=pd.Timestamp("2025-01-12T00:00:00Z"),
            horizons_at_least=None,
            horizons_at_most=None,
            policy_issue_time=issue_time,
        ),
    )

    series = spec._load_series()

    # One value per event after duplicate collapse.
    assert not series.index.duplicated().any()
    assert series.loc[pd.Timestamp("2025-01-09T00:00:00Z")] == 10.0  # historical -> flex.service
    assert series.loc[pd.Timestamp("2025-01-11T00:00:00Z")] == 21.0  # future -> Thiink forecaster
