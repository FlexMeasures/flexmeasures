"""KPI endpoint tests that need an isolated database.

These live apart from test_assets_api.py because mixing the module-scoped ``db``
fixture with the function-scoped ``fresh_db`` fixture can leave open connections
while ``fresh_db`` recreates the tables.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import url_for
import pytest

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief


def _asset_with_daily_kpi(
    fresh_db,
    requesting_user,
    source,
    values: list[float | None],
    window_start: datetime,
) -> GenericAsset:
    asset_type = GenericAssetType(name="KPI test asset")
    asset = GenericAsset(
        name="KPI test asset",
        generic_asset_type=asset_type,
        account_id=requesting_user.account_id,
    )
    sensor = Sensor(
        name="Daily KPI",
        generic_asset=asset,
        event_resolution=timedelta(days=1),
        unit="MWh",
    )
    fresh_db.session.add_all([asset_type, asset, sensor])
    fresh_db.session.flush()
    fresh_db.session.add_all(
        [
            TimedBelief(
                event_start=window_start + timedelta(days=day),
                belief_horizon=timedelta(0),
                event_value=value,
                sensor=sensor,
                source=source,
                cumulative_probability=0.5,
            )
            for day, value in enumerate(values)
        ]
    )
    asset.sensors_to_show_as_kpis = [
        {"title": "Average", "sensor": sensor.id, "function": "mean"}
    ]
    fresh_db.session.flush()
    return asset


def _get_kpis(client, asset: GenericAsset, start: datetime, end: datetime) -> dict:
    response = client.get(
        url_for("AssetAPI:get_kpis", id=asset.id),
        query_string={"start": start.isoformat(), "end": end.isoformat()},
    )
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_kpi_response_reports_whether_selected_days_are_missing(
    fresh_db,
    client,
    setup_api_fresh_test_data,
    setup_sources_fresh_db,
    requesting_user,
):
    window_start = datetime(2025, 1, 1, tzinfo=ZoneInfo("Europe/Amsterdam"))
    asset = _asset_with_daily_kpi(
        fresh_db,
        requesting_user,
        setup_sources_fresh_db["Seita"],
        [2, 4, 6],
        window_start,
    )

    complete = _get_kpis(client, asset, window_start, window_start + timedelta(days=3))
    assert complete["has_missing_kpi_days"] is False
    assert complete["data"][0]["downsample_value"] == pytest.approx(4)

    incomplete = _get_kpis(
        client, asset, window_start, window_start + timedelta(days=4)
    )
    assert incomplete["has_missing_kpi_days"] is True
    assert incomplete["data"][0]["downsample_value"] == pytest.approx(4)


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_null_kpi_value_counts_as_a_missing_day(
    fresh_db,
    client,
    setup_api_fresh_test_data,
    setup_sources_fresh_db,
    requesting_user,
):
    window_start = datetime(2025, 2, 1, tzinfo=ZoneInfo("Europe/Amsterdam"))
    asset = _asset_with_daily_kpi(
        fresh_db,
        requesting_user,
        setup_sources_fresh_db["Seita"],
        [2, None, 4],
        window_start,
    )

    response = _get_kpis(client, asset, window_start, window_start + timedelta(days=3))
    assert response["has_missing_kpi_days"] is True
    assert response["data"][0]["downsample_value"] == pytest.approx(3)


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_complete_kpi_range_across_dst_has_no_missing_days(
    fresh_db,
    client,
    setup_api_fresh_test_data,
    setup_sources_fresh_db,
    requesting_user,
):
    window_start = datetime(2025, 3, 29, tzinfo=ZoneInfo("Europe/Amsterdam"))
    asset = _asset_with_daily_kpi(
        fresh_db,
        requesting_user,
        setup_sources_fresh_db["Seita"],
        [2, 4],
        window_start,
    )

    response = _get_kpis(client, asset, window_start, window_start + timedelta(days=2))
    assert response["has_missing_kpi_days"] is False
