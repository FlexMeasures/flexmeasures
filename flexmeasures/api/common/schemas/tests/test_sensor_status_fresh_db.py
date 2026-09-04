"""Status page tests that need a fresh database.

These live apart from test_sensor_data_schema.py on purpose: a module that mixes the module-scoped `db` fixture with the function-scoped `fresh_db` one can hang,
because `fresh_db` drops all tables while the module-scoped connection is still open.
"""

from datetime import timedelta

import pandas as pd

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.sensors import (
    get_statuses,
    serialize_sensor_status_data,
)


def test_get_status_data_recorded_ahead_of_its_knowledge_time(
    fresh_db, add_market_prices_fresh_db, setup_sources_fresh_db
):
    """A sensor whose most recent data is not knowable yet has data, and is not stale.

    Regression test for a day-ahead price sensor on the status page,
    which reported "no data recorded" and showed a red light,
    because tomorrow's prices were recorded ahead of their knowledge time.
    """
    sensor = add_market_prices_fresh_db["epex_da"]

    # Record tomorrow's prices at 09:00, three hours ahead of their knowledge time of 12:00.
    event_starts = initialize_index(
        start=pd.Timestamp("2016-01-05").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2016-01-06").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    fresh_db.session.add_all(
        [
            TimedBelief(
                event_start=event_start,
                belief_horizon=timedelta(hours=3),
                event_value=10,
                sensor=sensor,
                source=setup_sources_fresh_db["Seita"],
            )
            for event_start in event_starts
        ]
    )
    fresh_db.session.flush()

    # An hour after recording those prices, but still an hour before their knowledge time
    now = pd.Timestamp("2016-01-04T10:00+01")

    sensor_statuses = get_statuses(sensor=sensor, now=now)
    demo_script_statuses = [
        status for status in sensor_statuses if status["source_type"] == "demo script"
    ]
    assert len(demo_script_statuses) == 1
    status = demo_script_statuses[0]
    assert status["stale"] is False
    assert status["staleness"] == timedelta(hours=2)
    assert status["reason"] == (
        "most recent data is 2 hours in the future, which is more recent than we could expect"
    )


def test_serialize_sensor_status_data_relation_to_other_asset(
    fresh_db, add_market_prices_fresh_db, add_battery_assets_fresh_db
):
    """The reported relation is about the asset whose status page we are on.

    Regression test for a price sensor of another asset, pulled in via the flex-context,
    being reported as belonging to the asset whose status page is shown.
    """
    price_sensor = add_market_prices_fresh_db["epex_da"]
    battery_asset = add_battery_assets_fresh_db["Test battery"]
    battery_asset.flex_context["consumption-price"] = {"sensor": price_sensor.id}
    fresh_db.session.add(battery_asset)
    fresh_db.session.flush()

    # On the status page of the battery, the price sensor is only related via the flex-context
    statuses = serialize_sensor_status_data(sensor=price_sensor, asset=battery_asset)
    assert statuses
    for status in statuses:
        assert status["asset_name"] == price_sensor.generic_asset.name
        assert "sensor belongs to this asset" not in status["relation"]
        assert (
            f"sensor belongs to asset '{price_sensor.generic_asset.name}'"
            in status["relation"]
        )
        assert "flex context (consumption-price)" in status["relation"]

    # Without an asset context, the sensor is reported relative to its own asset
    statuses = serialize_sensor_status_data(sensor=price_sensor)
    assert statuses
    for status in statuses:
        assert "sensor belongs to this asset" in status["relation"]


def test_get_status_unknown_source_type(
    fresh_db, add_market_prices_fresh_db, setup_sources_fresh_db
):
    """A sensor recorded by a source type FlexMeasures does not know about is still reported on.

    Regression test for the toy tutorial's day-ahead price sensor reporting "no data recorded",
    because the CLI recorded its prices under the source type "CLI script",
    which is not one of the default source types.
    """
    sensor = add_market_prices_fresh_db["epex_da"]
    cli_source = DataSource(name="toy-user", type="CLI script")
    fresh_db.session.add(cli_source)
    event_starts = initialize_index(
        start=pd.Timestamp("2016-01-05").tz_localize("Europe/Amsterdam"),
        end=pd.Timestamp("2016-01-06").tz_localize("Europe/Amsterdam"),
        resolution="1H",
    )
    fresh_db.session.add_all(
        [
            TimedBelief(
                event_start=event_start,
                belief_horizon=timedelta(hours=3),
                event_value=10,
                sensor=sensor,
                source=cli_source,
            )
            for event_start in event_starts
        ]
    )
    fresh_db.session.flush()

    sensor_statuses = get_statuses(
        sensor=sensor, now=pd.Timestamp("2016-01-04T10:00+01")
    )
    cli_statuses = [
        status for status in sensor_statuses if status["source_type"] == "CLI script"
    ]
    assert len(cli_statuses) == 1
    assert cli_statuses[0]["stale"] is False
