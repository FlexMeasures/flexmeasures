"""Reusable demo price data for trying out scheduling."""

from datetime import datetime, timedelta, timezone

from marshmallow import ValidationError

from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.data_sources import get_or_create_source
from flexmeasures.utils.time_utils import server_now


def create_demo_price_sensor(
    asset: GenericAsset,
    start_time: datetime,
    end_time: datetime,
    *,
    price: float = 100,
    unit: str = "EUR/MWh",
) -> Sensor:
    """Create hourly, fixed demo prices covering a planning period.

    The beliefs are available at creation time, including for future events. The
    caller owns the transaction and should obtain permission to edit sensors.
    """
    if (
        start_time.tzinfo is None
        or end_time.tzinfo is None
        or not timedelta(0) < end_time - start_time <= timedelta(days=31)
    ):
        raise ValidationError(
            "Choose a period of at most 31 days with timezone-aware times."
        )
    resolution = timedelta(hours=1)
    start_utc = start_time.astimezone(timezone.utc)
    first_event = start_utc.replace(minute=0, second=0, microsecond=0)
    sensor = Sensor(
        name="Demo electricity price",
        unit=unit,
        generic_asset=asset,
        event_resolution=resolution,
        attributes={"demo_data": True},
    )
    db.session.add(sensor)
    source = get_or_create_source(
        "FlexMeasures demo prices", source_type="demo", account=asset.owner
    )
    known_at = server_now()
    event_start = first_event
    while event_start < end_time:
        db.session.add(
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                event_value=price,
                belief_horizon=event_start + resolution - known_at,
            )
        )
        event_start += resolution
    db.session.flush()
    AssetAuditLog.add_record(
        asset, f"Created demo price sensor '{sensor.name}': {sensor.id}"
    )
    return sensor
