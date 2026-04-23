from __future__ import annotations

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),
    ],
    indirect=["requesting_user"],
)
def test_get_sources_missing_auth(client, requesting_user, status_code):
    """Unauthenticated requests must be rejected."""
    get_sources_response = client.get(url_for("SourceAPI:index"))
    print("Server responded with:\n%s" % get_sources_response.data)
    assert get_sources_response.status_code == status_code


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_structure(client, setup_api_test_data, requesting_user):
    """The response must contain a 'types' list and a 'sources' list."""
    response = client.get(url_for("SourceAPI:index"))
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    data = response.json
    assert "types" in data
    assert "sources" in data
    assert isinstance(data["types"], list)
    assert isinstance(data["sources"], list)
    # Default types must be present
    for t in [
        "user",
        "scheduler",
        "forecaster",
        "reporter",
        "demo script",
        "gateway",
        "market",
    ]:
        assert t in data["types"]
    # Each source entry must carry at minimum id, name, type and description
    for source in data["sources"]:
        assert "id" in source
        assert "name" in source
        assert "type" in source
        assert "description" in source


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_access_limited(client, setup_api_test_data, requesting_user, db):
    """A regular user must NOT see sources that belong to a different account.

    The test:
    1. Creates a data source bound to the supplier account (inaccessible to the prosumer).
    2. Verifies the prosumer does NOT see that source in the response.
    3. Verifies an admin DOES see it.
    """
    prosumer_user = find_user_by_email("test_prosumer_user@seita.nl")
    supplier_user = find_user_by_email("test_supplier_user_4@seita.nl")

    # Create an account-bound source that the prosumer cannot access
    private_source = DataSource(
        name="PrivateSupplierSource",
        type="demo script",
        account=supplier_user.account,
    )
    db.session.add(private_source)
    db.session.flush()
    private_source_id = private_source.id

    # Prosumer: should NOT see the private supplier source
    response = client.get(url_for("SourceAPI:index"))
    assert response.status_code == 200
    source_ids = [s["id"] for s in response.json["sources"]]
    assert private_source_id not in source_ids

    # Prosumer should see their own user's data source (if any)
    prosumer_ds_ids = [
        ds.id
        for ds in db.session.scalars(
            select(DataSource).where(DataSource.account_id == prosumer_user.account_id)
        ).all()
    ]
    for ds_id in prosumer_ds_ids:
        assert ds_id in source_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_admin_user@seita.nl"],
    indirect=True,
)
def test_get_sources_admin_sees_all(client, setup_api_test_data, requesting_user, db):
    """An admin must see ALL data sources, including private ones."""
    # Count all sources in DB
    total_sources = db.session.scalars(select(DataSource)).all()
    response = client.get(url_for("SourceAPI:index"))
    assert response.status_code == 200
    source_ids = {s["id"] for s in response.json["sources"]}
    for ds in total_sources:
        assert ds.id in source_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_consultant@seita.nl"],
    indirect=True,
)
def test_get_sources_consultant_sees_client_sources(
    client, setup_api_test_data, requesting_user, db
):
    """A consultant must see sources of their consultancy-client accounts."""
    consultant_user = find_user_by_email("test_consultant@seita.nl")
    # Consultant account should have at least one consultancy client
    client_accounts = consultant_user.account.consultancy_client_accounts
    assert len(client_accounts) > 0

    # Create a source bound to a client account
    client_account = client_accounts[0]
    client_source = DataSource(
        name="ConsultancyClientSource",
        type="demo script",
        account=client_account,
    )
    db.session.add(client_source)
    db.session.flush()
    client_source_id = client_source.id

    response = client.get(url_for("SourceAPI:index"))
    assert response.status_code == 200
    source_ids = [s["id"] for s in response.json["sources"]]
    assert client_source_id in source_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_only_latest(client, setup_api_test_data, requesting_user, db):
    """The only_latest toggle must return at most one source per (name, type, model) group."""
    # Create two versioned sources in the same group, both public (no account_id / user_id)
    source_v1 = DataSource(
        name="VersionedScheduler",
        type="scheduler",
        model="TestModel",
        version="1.0",
    )
    source_v2 = DataSource(
        name="VersionedScheduler",
        type="scheduler",
        model="TestModel",
        version="2.0",
    )
    db.session.add_all([source_v1, source_v2])
    db.session.flush()

    # Without the toggle both versions are returned
    response_all = client.get(url_for("SourceAPI:index"))
    assert response_all.status_code == 200
    all_ids = [s["id"] for s in response_all.json["sources"]]
    assert source_v1.id in all_ids
    assert source_v2.id in all_ids

    # With the toggle only the latest version is returned
    response_latest = client.get(
        url_for("SourceAPI:index"), query_string={"only_latest": True}
    )
    assert response_latest.status_code == 200
    latest_ids = [s["id"] for s in response_latest.json["sources"]]
    # v2 (higher version) must be present, v1 must be absent
    assert source_v2.id in latest_ids
    assert source_v1.id not in latest_ids
