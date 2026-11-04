from __future__ import annotations

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.data_sources import get_or_create_source
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
    """The endpoint should default to latest-only and allow opting out via only_latest=false."""
    # Create two versioned sources in the same group, both of the organisation whose sources the user may read
    source_v1 = DataSource(
        name="VersionedScheduler",
        type="scheduler",
        model="TestModel",
        version="1.0",
        account_id=requesting_user.account_id,
    )
    source_v2 = DataSource(
        name="VersionedScheduler",
        type="scheduler",
        model="TestModel",
        version="2.0",
        account_id=requesting_user.account_id,
    )
    db.session.add_all([source_v1, source_v2])
    db.session.flush()

    # By default only the latest version is returned
    response_default = client.get(url_for("SourceAPI:index"))
    assert response_default.status_code == 200
    default_ids = [s["id"] for s in response_default.json["sources"]]
    assert source_v2.id in default_ids
    assert source_v1.id not in default_ids

    # Callers can opt out of deduplication and request all versions explicitly
    response_all = client.get(
        url_for("SourceAPI:index"), query_string={"only_latest": False}
    )
    assert response_all.status_code == 200
    all_ids = [s["id"] for s in response_all.json["sources"]]
    assert source_v1.id in all_ids
    assert source_v2.id in all_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_admin_user@seita.nl"],
    indirect=True,
)
def test_get_sources_only_latest_preserves_different_accounts(
    client, setup_api_test_data, requesting_user, db
):
    """only_latest must NOT collapse sources with the same name/type/model but different account_ids.

    Two accessible sources that share the same generator identity but belong to
    different organisations are distinct lineages and must both survive the
    deduplication step.
    """
    prosumer_user = find_user_by_email("test_prosumer_user@seita.nl")
    supplier_user = find_user_by_email("test_supplier_user_4@seita.nl")

    source_account_a = DataSource(
        name="SharedScheduler",
        type="scheduler",
        model="StorageScheduler",
        version="1.0",
        account_id=prosumer_user.account_id,
    )
    source_account_b = DataSource(
        name="SharedScheduler",
        type="scheduler",
        model="StorageScheduler",
        version="1.0",
        account_id=supplier_user.account_id,
    )
    db.session.add_all([source_account_a, source_account_b])
    db.session.flush()

    response = client.get(
        url_for("SourceAPI:index"), query_string={"only_latest": True}
    )
    assert response.status_code == 200
    latest_ids = [s["id"] for s in response.json["sources"]]
    # Both sources must be present because they belong to different accounts
    assert source_account_a.id in latest_ids
    assert source_account_b.id in latest_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_user_id_rule(client, setup_api_test_data, requesting_user, db):
    """A source with a user_id but no account_id must not be visible to a regular user.

    The public/system filter requires *both* account_id IS NULL and user_id IS NULL.
    A source that is user-owned (user_id set) but not account-affiliated should
    therefore be hidden from callers who do not belong to that user's account.
    """
    # Create a source with user_id set but no account affiliation.
    # Since every real user already has a DataSource (unique constraint on user_id),
    # we use a sentinel id far outside the range of real test users.  There is no
    # DB-level FK on user_id, so this is safe.
    _FAKE_USER_ID = 99_999
    user_owned_source = DataSource(
        name="UserOwnedSource",
        type="demo script",
    )
    user_owned_source.user_id = _FAKE_USER_ID
    db.session.add(user_owned_source)
    db.session.flush()

    response = client.get(url_for("SourceAPI:index"))
    assert response.status_code == 200
    source_ids = [s["id"] for s in response.json["sources"]]
    assert user_owned_source.id not in source_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_only_latest_tie_break_by_id(
    client, setup_api_test_data, requesting_user, db
):
    """When two sources share the same version, the one with the higher id must win.

    This covers the documented tie-break rule in _filter_sources_to_latest.
    """
    # Identical sources are refused, but a scheduler has one source per flex config it computed under.
    source_lower_id = DataSource(
        name="TieBreakScheduler",
        type="scheduler",
        model="TieModel",
        version="1.0",
        account_id=requesting_user.account_id,
        attributes={"data_generator": {"config": {"flex-context": "a"}}},
    )
    source_higher_id = DataSource(
        name="TieBreakScheduler",
        type="scheduler",
        model="TieModel",
        version="1.0",
        account_id=requesting_user.account_id,
        attributes={"data_generator": {"config": {"flex-context": "b"}}},
    )
    db.session.add(source_lower_id)
    db.session.flush()
    db.session.add(source_higher_id)
    db.session.flush()
    # Ensure the expected ID ordering holds
    assert source_higher_id.id > source_lower_id.id

    response = client.get(
        url_for("SourceAPI:index"), query_string={"only_latest": True}
    )
    assert response.status_code == 200
    latest_ids = [s["id"] for s in response.json["sources"]]
    # Higher id must win the tie
    assert source_higher_id.id in latest_ids
    assert source_lower_id.id not in latest_ids


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_source(client, setup_api_test_data, requesting_user, db):
    """One data source can be looked up in full, including its attributes."""
    prosumer_user = find_user_by_email("test_prosumer_user@seita.nl")
    source = DataSource(
        name="SomeForecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        version="1",
        account=prosumer_user.account,
        attributes={"data_generator": {"config": {"model": "CustomLGBM"}}},
    )
    db.session.add(source)
    db.session.flush()

    response = client.get(url_for("SourceAPI:get", id=source.id))
    assert response.status_code == 200
    assert response.json["id"] == source.id
    assert response.json["name"] == "SomeForecaster"
    assert response.json["model"] == "TrainPredictPipeline"
    assert response.json["user_id"] is None  # unset fields are shown, too
    assert response.json["attributes"] == {
        "data_generator": {"config": {"model": "CustomLGBM"}}
    }


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 403),  # different account
        ("test_admin_user@seita.nl", 200),  # admins see all sources
    ],
    indirect=["requesting_user"],
)
def test_get_source_auth(
    client, setup_api_test_data, requesting_user, expected_status_code, db
):
    """A data source of another account cannot be looked up."""
    supplier_user = find_user_by_email("test_supplier_user_4@seita.nl")
    # An earlier test may have set up this source already.
    source = get_or_create_source(
        "PrivateSupplierSource",
        source_type="demo script",
        account=supplier_user.account,
    )

    response = client.get(url_for("SourceAPI:get", id=source.id))
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_nonexistent_source(client, setup_api_test_data, requesting_user):
    response = client.get(url_for("SourceAPI:get", id=99999))
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user",
    ["test_admin_user@seita.nl"],
    indirect=True,
)
def test_get_sources_filtered_by_type_and_search_term(
    client, setup_api_test_data, requesting_user, db
):
    """The listing can be narrowed to one source type, and searched by name, by model and by id."""
    forecaster = DataSource(
        name="SearchableSeita",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    reporter = DataSource(
        name="SearchableSeita",
        type="reporter",
        model="PandasReporter",
    )
    db.session.add_all([forecaster, reporter])
    db.session.flush()

    by_type = client.get(url_for("SourceAPI:index"), query_string={"type": "reporter"})
    assert by_type.status_code == 200
    assert {source["type"] for source in by_type.json["sources"]} == {"reporter"}
    assert reporter.id in {source["id"] for source in by_type.json["sources"]}
    assert forecaster.id not in {source["id"] for source in by_type.json["sources"]}

    by_model = client.get(
        url_for("SourceAPI:index"), query_string={"filter": "TrainPredictPipeline"}
    )
    assert by_model.status_code == 200
    assert forecaster.id in {source["id"] for source in by_model.json["sources"]}
    assert reporter.id not in {source["id"] for source in by_model.json["sources"]}

    by_name = client.get(
        url_for("SourceAPI:index"), query_string={"filter": "searchableseita"}
    )
    assert by_name.status_code == 200
    assert {forecaster.id, reporter.id} <= {
        source["id"] for source in by_name.json["sources"]
    }

    by_id = client.get(
        url_for("SourceAPI:index"),
        query_string={"filter": str(forecaster.id), "only_latest": "false"},
    )
    assert by_id.status_code == 200
    assert forecaster.id in {source["id"] for source in by_id.json["sources"]}


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_limit_returns_the_newest_ones(
    client, setup_api_test_data, requesting_user, db
):
    """A limited listing holds that many sources, the most recently created ones, in a stable order."""
    sources = [
        DataSource(
            name=f"LimitedSeita{index}",
            type="forecaster",
            model="Pipeline",
            account_id=requesting_user.account_id,
        )
        for index in range(4)
    ]
    db.session.add_all(sources)
    db.session.flush()
    newest_two = [source.id for source in sorted(sources, key=lambda s: -s.id)][:2]

    limited = client.get(
        url_for("SourceAPI:index"),
        query_string={"filter": "LimitedSeita", "only_latest": "false", "limit": 2},
    )
    assert limited.status_code == 200
    assert [source["id"] for source in limited.json["sources"]] == newest_two

    unlimited = client.get(
        url_for("SourceAPI:index"),
        query_string={"filter": "LimitedSeita", "only_latest": "false"},
    )
    assert unlimited.status_code == 200
    assert len(unlimited.json["sources"]) == 4


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_get_sources_types_are_not_narrowed_by_the_filters(
    client, setup_api_test_data, requesting_user, db
):
    """The types cover every source the user may read, so that one call can both search and offer the types to search by."""
    db.session.add(
        DataSource(
            name="TypedSeita",
            type="soothsayer",
            model="CrystalBall",
            account_id=requesting_user.account_id,
        )
    )
    db.session.flush()

    unfiltered = client.get(url_for("SourceAPI:index"))
    assert unfiltered.status_code == 200
    assert "soothsayer" in unfiltered.json["types"]

    filtered = client.get(
        url_for("SourceAPI:index"), query_string={"type": "scheduler"}
    )
    assert filtered.status_code == 200
    assert "soothsayer" not in {source["type"] for source in filtered.json["sources"]}
    assert "soothsayer" in filtered.json["types"]


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_belonging_to_no_organisation_does_not_make_a_source_readable(
    client, setup_api_test_data, requesting_user, db
):
    """A data generator's source used to belong to no organisation, which made every one of them readable by everybody."""
    orphan = DataSource(
        name="OrphanForecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {"model": "CustomLGBM"}}},
    )
    db.session.add(orphan)
    db.session.flush()

    listing = client.get(
        url_for("SourceAPI:index"), query_string={"filter": "OrphanForecaster"}
    )
    assert listing.status_code == 200
    assert listing.json["sources"] == []

    detail = client.get(url_for("SourceAPI:get", id=orphan.id))
    assert detail.status_code == 403


@pytest.mark.parametrize(
    "requesting_user",
    ["test_supplier_user_4@seita.nl"],
    indirect=True,
)
def test_a_source_recorded_on_a_readable_sensor_hands_over_no_configuration(
    client, setup_api_test_data, requesting_user, db
):
    """What computed a number one may see is a fair question, but the answer must not name another organisation's sensors."""
    from flexmeasures.data.models.data_sources import SensorDataSource

    gas_sensor = setup_api_test_data["some gas sensor"]
    prosumer_user = find_user_by_email("test_prosumer_user@seita.nl")
    foreign = DataSource(
        name="ForeignForecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        account=prosumer_user.account,
        attributes={"data_generator": {"config": {"sensor": 404}}},
    )
    db.session.add(foreign)
    db.session.flush()
    db.session.add(SensorDataSource(sensor_id=gas_sensor.id, source_id=foreign.id))
    db.session.flush()

    detail = client.get(url_for("SourceAPI:get", id=foreign.id))
    assert detail.status_code == 200
    assert detail.json["id"] == foreign.id
    assert "attributes" not in detail.json

    # Recording on a sensor is not what makes a source one to reuse, so it stays out of the listing.
    listing = client.get(
        url_for("SourceAPI:index"), query_string={"filter": "ForeignForecaster"}
    )
    assert listing.status_code == 200
    assert listing.json["sources"] == []


@pytest.mark.parametrize(
    "requesting_user",
    ["test_prosumer_user@seita.nl"],
    indirect=True,
)
def test_an_automation_of_ones_own_makes_its_source_readable(
    client, setup_api_test_data, requesting_user, db
):
    """A source one's own automation computes under is one's own to work with, before it has recorded anything."""
    from flexmeasures.data.models.automations import Automation
    from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType

    asset = GenericAsset(
        name="automated site",
        generic_asset_type=db.session.scalars(select(GenericAssetType)).first(),
        account_id=requesting_user.account_id,
    )
    db.session.add(asset)
    db.session.flush()
    source = DataSource(
        name="AutomatedForecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {"model": "CustomLGBM"}}},
    )
    db.session.add(source)
    db.session.flush()
    db.session.add(
        Automation(
            asset_id=asset.id,
            type="forecasting",
            name="Hourly forecasts",
            cronstr="0 * * * *",
            timezone="Europe/Amsterdam",
            generator_id=source.id,
        )
    )
    db.session.flush()

    listing = client.get(
        url_for("SourceAPI:index"), query_string={"filter": "AutomatedForecaster"}
    )
    assert listing.status_code == 200
    assert [s["id"] for s in listing.json["sources"]] == [source.id]

    detail = client.get(url_for("SourceAPI:get", id=source.id))
    assert detail.status_code == 200
    assert detail.json["attributes"] == {
        "data_generator": {"config": {"model": "CustomLGBM"}}
    }
