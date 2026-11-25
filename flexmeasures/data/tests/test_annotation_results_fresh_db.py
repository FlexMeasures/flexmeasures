"""Versions of annotations, of which a search can return only the most recent one, as for beliefs."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor

WINDOW = (
    pd.Timestamp("2026-11-12T00:00:00+01:00"),
    pd.Timestamp("2026-11-12T12:00:00+01:00"),
)
RUN = pd.Timestamp("2026-11-12T12:00:00+01:00")


def at(time: str) -> pd.Timestamp:
    return pd.Timestamp(f"2026-11-12T{time}:00+01:00")


@pytest.fixture
def meter(fresh_db) -> dict:
    asset_type = GenericAssetType(name="site")
    asset = GenericAsset(name="site", generic_asset_type=asset_type)
    sensor = Sensor(
        name="meter",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="Europe/Amsterdam",
    )
    source = DataSource(name="gap check", type="reporter")
    other_source = DataSource(name="another check", type="reporter")
    fresh_db.session.add_all([asset_type, asset, sensor, source, other_source])
    fresh_db.session.commit()
    return dict(sensor=sensor, source=source, other_source=other_source)


def current(meter, **kwargs) -> list[tuple[str, str, str, str]]:
    """The most recent version of each finding on the meter, as (start, end, type, content)."""
    return sorted(
        (
            a.start.astimezone(WINDOW[0].tz).strftime("%H:%M"),
            a.end.astimezone(WINDOW[0].tz).strftime("%H:%M"),
            a.type,
            a.content,
        )
        for a in meter["sensor"].search_annotations(
            most_recent_beliefs_only=True, **kwargs
        )
    )


# ― Showing only the most recent version ――――――――――――――――――――――――――――――――――――――――――――――――――


def annotate(meter, start, end, annotation_type, belief_time, source=None):
    meter["sensor"].annotations.append(
        Annotation(
            start=at(start),
            end=at(end),
            type=annotation_type,
            content=f"{annotation_type} from {start}",
            belief_time=belief_time,
            source=source or meter["source"],
        )
    )


def test_only_the_most_recent_version_of_an_annotation_is_shown(meter, fresh_db):
    """An annotation is identified by its subject, source and start, so these are three versions of one, plus one of another source."""
    annotate(meter, "03:00", "04:00", "warning", at("04:00"))
    annotate(meter, "03:00", "06:00", "alert", at("06:00"))
    annotate(meter, "03:00", "05:00", "label", at("08:00"))
    annotate(meter, "03:00", "04:00", "warning", at("04:00"), meter["other_source"])
    fresh_db.session.flush()

    assert current(meter) == [
        ("03:00", "04:00", "warning", "warning from 03:00"),
        ("03:00", "05:00", "label", "label from 03:00"),
    ]
    # Without opting in, every version is returned, as before
    assert len(meter["sensor"].search_annotations()) == 4
    # Replaying an earlier moment shows the version known then
    assert current(meter, beliefs_before=at("07:00"), source=meter["source"]) == [
        ("03:00", "06:00", "alert", "alert from 03:00")
    ]
    # The window is applied after the most recent version is picked,
    # so an older version reaching into the window does not show when the most recent one does not
    assert current(meter, annotations_after=at("05:30")) == []


def test_without_belief_times_the_last_recorded_version_counts(meter, fresh_db):
    annotate(meter, "03:00", "04:00", "label", None)
    annotate(meter, "03:00", "05:00", "label", None)
    fresh_db.session.flush()
    assert current(meter) == [("03:00", "05:00", "label", "label from 03:00")]

    # A version with a belief time is more recent than one without
    annotate(meter, "03:00", "06:00", "warning", at("01:00"))
    fresh_db.session.flush()
    assert current(meter) == [("03:00", "06:00", "warning", "warning from 03:00")]


def test_an_asset_search_picks_the_most_recent_version_before_the_type(meter, fresh_db):
    """An alert that was resolved is no alert any more, even though an older version of it was."""
    asset = meter["sensor"].generic_asset
    for annotation_type, belief_time in (
        ("alert", at("04:00")),
        ("label", at("05:00")),
    ):
        asset.annotations.append(
            Annotation(
                start=at("03:00"),
                end=at("04:00"),
                type=annotation_type,
                content=annotation_type,
                belief_time=belief_time,
                source=meter["source"],
            )
        )
    fresh_db.session.flush()

    assert asset.search_annotations(annotation_type="alert") != []
    assert (
        asset.search_annotations(annotation_type="alert", most_recent_beliefs_only=True)
        == []
    )
