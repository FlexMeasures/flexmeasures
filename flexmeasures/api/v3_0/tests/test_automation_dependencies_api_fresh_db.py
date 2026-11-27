"""Naming the automations an automation waits for, through the API."""

from datetime import timedelta

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.automations import (
    Automation,
    AutomationDependency,
    AutomationRun,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture
def upstream_automations(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """An automation on the prosumer's own battery, one on a public asset, and one on the supplier's wind turbine, all recurring at 06:00 UTC."""
    assets = setup_generic_assets_fresh_db
    battery = assets["test_battery"]
    sensor = Sensor(
        name="battery power",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=battery,
    )
    generator = DataSource(
        name="forecaster", type="forecaster", model="TrainPredictPipeline"
    )
    fresh_db.session.add_all([sensor, generator])
    fresh_db.session.flush()
    automations = {
        key: Automation(
            asset=assets[asset_key],
            generator=generator,
            type="forecasting",
            name=f"Upstream on {asset_key}",
            cronstr="0 6 * * *",
            timezone="UTC",
            parameters={},
        )
        for key, asset_key in (
            ("own", "test_battery"),
            ("public", "troposphere"),
            ("foreign", "test_wind_turbine"),
        )
    }
    fresh_db.session.add_all(automations.values())
    fresh_db.session.commit()
    return battery, sensor, automations


def _waits_for(response) -> list[dict]:
    """What a response says an automation waits for, without what it tells about those automations."""
    return [
        {key: dependency[key] for key in ("automation", "allow-failure")}
        for dependency in response.json["depends-on"]
    ]


def _post(client, battery, sensor, depends_on, cron="0 6 * * *"):
    return client.post(
        url_for("AssetAPI:post_automation", id=battery.id),
        json={
            "name": "Downstream forecasts",
            "cron": cron,
            "timezone": "UTC",
            "type": "forecasting",
            "parameters": {"sensor": sensor.id},
            "depends-on": depends_on,
        },
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_waiting_for_readable_automations(
    app, fresh_db, upstream_automations, requesting_user
):
    """Upstream automations can be on the user's own assets and on public ones, and the response names them."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = _post(
            client,
            battery,
            sensor,
            [
                {"automation": upstream["own"].id},
                {"automation": upstream["public"].id, "allow-failure": True},
            ],
        )
        assert response.status_code == 201, response.json
        assert _waits_for(response) == [
            {"automation": upstream["own"].id, "allow-failure": False},
            {"automation": upstream["public"].id, "allow-failure": True},
        ]
        listing = client.get(url_for("AssetAPI:get_automations", id=battery.id))
    listed = {
        automation["id"]: automation for automation in listing.json["automations"]
    }
    assert listed[response.json["id"]]["depends-on"] == response.json["depends-on"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_an_upstream_automation_is_only_described_to_who_may_read_it(
    app, fresh_db, upstream_automations, requesting_user
):
    """One a user may read comes with its name and asset, while one they may not read gives nothing away but its ID."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = _post(client, battery, sensor, [{"automation": upstream["own"].id}])
        assert response.status_code == 201, response.json
        # The API refuses to wait for an automation one may not read, but access to one can be lost later on.
        fresh_db.session.add(
            AutomationDependency(
                automation_id=response.json["id"],
                upstream_id=upstream["foreign"].id,
                allow_failure=False,
            )
        )
        fresh_db.session.commit()
        listing = client.get(url_for("AssetAPI:get_automations", id=battery.id))
    listed = {
        automation["id"]: automation for automation in listing.json["automations"]
    }
    described = {
        dependency["automation"]: dependency
        for dependency in listed[response.json["id"]]["depends-on"]
    }
    assert described[upstream["own"].id] == {
        "automation": upstream["own"].id,
        "allow-failure": False,
        "name": "Upstream on test_battery",
        "asset": battery.id,
        "asset-name": battery.name,
    }
    assert described[upstream["foreign"].id] == {
        "automation": upstream["foreign"].id,
        "allow-failure": False,
    }


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_refuses_to_wait_for_an_unreadable_automation(
    app, fresh_db, upstream_automations, requesting_user
):
    """An automation one may not read gets the answer of one that does not exist, so that IDs reveal nothing."""
    battery, sensor, upstream = upstream_automations
    foreign_id = upstream["foreign"].id
    unknown_id = foreign_id + 1000
    with app.test_client() as client:
        foreign = _post(client, battery, sensor, [{"automation": foreign_id}])
        unknown = _post(client, battery, sensor, [{"automation": unknown_id}])
    assert foreign.status_code == unknown.status_code == 422, foreign.json
    assert foreign.get_data(as_text=True).replace(
        str(foreign_id), "<id>"
    ) == unknown.get_data(as_text=True).replace(str(unknown_id), "<id>")


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_waiting_for_one_on_another_schedule(
    app, fresh_db, upstream_automations, requesting_user
):
    """A run waits for the latest upstream run due at or before its own time, so the schedules need not match."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = _post(
            client,
            battery,
            sensor,
            [{"automation": upstream["own"].id}],
            cron="0 7 * * *",
        )
    assert response.status_code == 201, response.json
    assert _waits_for(response) == [
        {"automation": upstream["own"].id, "allow-failure": False}
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_automation_dependencies(
    app, fresh_db, upstream_automations, requesting_user
):
    """Dependencies can be replaced and cleared, and the schedule can change while they stay."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        created = _post(client, battery, sensor, [{"automation": upstream["own"].id}])
        assert created.status_code == 201, created.json
        url = url_for(
            "AssetAPI:patch_automation", id=battery.id, automation_id=created.json["id"]
        )

        moved = client.patch(url, json={"cron": "0 7 * * *"})
        assert moved.status_code == 200, moved.json
        assert _waits_for(moved) == [
            {"automation": upstream["own"].id, "allow-failure": False}
        ]

        replaced = client.patch(
            url,
            json={
                "depends-on": [
                    {"automation": upstream["public"].id, "allow-failure": True}
                ]
            },
        )
        assert replaced.status_code == 200, replaced.json
        assert _waits_for(replaced) == [
            {"automation": upstream["public"].id, "allow-failure": True}
        ]

        cleared = client.patch(url, json={"depends-on": []})
    assert cleared.status_code == 200, cleared.json
    assert cleared.json["depends-on"] == []
    assert cleared.json["cron"] == "0 7 * * *"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_automation_refuses_to_wait_for_an_unreadable_automation(
    app, fresh_db, upstream_automations, requesting_user
):
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=upstream["own"].id,
            ),
            json={"depends-on": [{"automation": upstream["foreign"].id}]},
        )
    assert response.status_code == 422, response.json
    fresh_db.session.expire_all()
    assert fresh_db.session.get(Automation, upstream["own"].id).dependencies == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_listing_automations_across_assets(
    app, fresh_db, upstream_automations, requesting_user
):
    """Public automations can be listed apart, and everything a user may read comes together, but nothing they may not read."""
    _, _, upstream = upstream_automations
    with app.test_client() as client:
        public = client.get(
            url_for("AssetAPI:get_automations_across_assets"),
            query_string={"scope": "public"},
        )
        everything = client.get(
            url_for("AssetAPI:get_automations_across_assets"),
            query_string={"scope": "all"},
        )
        unknown = client.get(
            url_for("AssetAPI:get_automations_across_assets"),
            query_string={"scope": "nonsense"},
        )
    assert public.status_code == 200, public.json
    assert [a["id"] for a in public.json["automations"]] == [upstream["public"].id]
    assert public.json["automations"][0]["asset-name"] == "troposphere"
    assert "num-records" not in public.json
    assert {a["id"] for a in everything.json["automations"]} == {
        upstream["own"].id,
        upstream["public"].id,
    }
    assert unknown.status_code == 422


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_listing_automations_across_assets_by_page(
    app, fresh_db, upstream_automations, requesting_user, monkeypatch
):
    """Pages are cut from what the user may read, so an automation they may not read takes no place on a page."""
    _, _, upstream = upstream_automations
    extra = Automation(
        name="Another public one",
        asset=upstream["public"].asset,
        type=upstream["public"].type,
        cronstr="0 * * * *",
        generator=upstream["public"].generator,
        parameters=dict(upstream["public"].parameters),
    )
    fresh_db.session.add(extra)
    fresh_db.session.commit()
    # Keep the user's own automation, which comes first by ID, from them.
    hidden = upstream["own"].id
    monkeypatch.setattr(
        "flexmeasures.api.v3_0.assets._may_read_automation",
        lambda automation: automation.id != hidden,
    )
    url = url_for("AssetAPI:get_automations_across_assets")
    with app.test_client() as client:
        pages = [
            client.get(url, query_string={"scope": "all", "page": page, "per-page": 1})
            for page in (1, 2, 3)
        ]
    assert [page.status_code for page in pages] == [200] * 3
    assert [[a["id"] for a in page.json["automations"]] for page in pages] == [
        [upstream["public"].id],
        [extra.id],
        [],
    ]
    assert {page.json["num-records"] for page in pages} == {2}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_automation_details_say_what_waits_for_it(
    app, fresh_db, upstream_automations, requesting_user
):
    """Before deleting an automation, one can ask what waits for it, also on another asset, without learning about what one may not read."""
    battery, sensor, upstream = upstream_automations
    downstream = _downstream_of(fresh_db, upstream, sensor, upstream["own"])
    fresh_db.session.add(
        AutomationDependency(
            automation_id=upstream["foreign"].id,
            upstream_id=upstream["own"].id,
            allow_failure=False,
        )
    )
    fresh_db.session.commit()
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=upstream["own"].id,
            ),
            query_string={"include": "waited-for-by"},
        )
        plain = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=upstream["own"].id,
            )
        )
    assert "waited-for-by" not in plain.json
    assert response.status_code == 200, response.json
    waiting = {item["automation"]: item for item in response.json["waited-for-by"]}
    assert waiting[downstream.id] == {
        "automation": downstream.id,
        "name": "Downstream",
        "asset": battery.id,
        "asset-name": battery.name,
    }
    assert waiting[upstream["foreign"].id] == {"automation": upstream["foreign"].id}


def _downstream_of(fresh_db, upstream, sensor, *upstreams) -> Automation:
    """An automation on the prosumer's battery that waits for these automations."""
    downstream = Automation(
        asset=upstream["own"].asset,
        generator=upstream["own"].generator,
        type="forecasting",
        name="Downstream",
        cronstr="0 6 * * *",
        timezone="UTC",
        parameters={"sensor": sensor.id},
    )
    fresh_db.session.add(downstream)
    fresh_db.session.flush()
    for automation in upstreams:
        fresh_db.session.add(
            AutomationDependency(
                automation_id=downstream.id,
                upstream_id=automation.id,
                allow_failure=False,
            )
        )
    fresh_db.session.commit()
    return downstream


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_run_plan_tells_what_will_run_and_what_will_not(
    app, fresh_db, upstream_automations, requesting_user
):
    """A public automation can be waited for but not run, which the plan says, another organisation's automation is left out, and the plan runs nothing."""
    battery, sensor, upstream = upstream_automations
    downstream = _downstream_of(
        fresh_db,
        upstream,
        sensor,
        upstream["own"],
        upstream["public"],
        upstream["foreign"],
    )
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation_run_plan",
                id=battery.id,
                automation_id=downstream.id,
            ),
            query_string={"include": "upstream"},
        )
    assert response.status_code == 200, response.json
    assert [step["automation"] for step in response.json["steps"]] == [
        upstream["own"].id,
        downstream.id,
    ]
    excluded = {step["automation"]: step for step in response.json["excluded"]}
    assert (
        excluded[upstream["public"].id]["reason"] == "You may not run this automation."
    )
    assert excluded[upstream["public"].id]["name"] == "Upstream on troposphere"
    assert upstream["foreign"].id not in excluded
    assert response.json["steps"][1]["waits-for"] == [
        upstream["own"].id,
        upstream["public"].id,
    ]
    assert excluded[upstream["public"].id]["last-succeeded-at"] is None
    assert fresh_db.session.scalars(select(AutomationRun)).all() == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_automation_with_upstream(
    app, fresh_db, upstream_automations, requesting_user
):
    """What the user may run runs first, what they may not is left out and reported, and what they leave out does not run."""
    battery, sensor, upstream = upstream_automations
    upstream["own"].parameters = {"sensor": sensor.id}
    downstream = _downstream_of(
        fresh_db, upstream, sensor, upstream["own"], upstream["public"]
    )
    url = url_for(
        "AssetAPI:trigger_automation", id=battery.id, automation_id=downstream.id
    )
    with app.test_client() as client:
        response = client.post(url, query_string={"with-upstream": "true"})
        assert response.status_code == 202, response.json
        assert [
            (run["automation"], run["dispatch-state"]) for run in response.json["runs"]
        ] == [(upstream["own"].id, "queued"), (downstream.id, "waiting")]
        assert response.json["excluded"] == [
            {
                "automation": upstream["public"].id,
                "reason": "You may not run this automation.",
            }
        ]

        excluded = client.post(
            url,
            query_string={
                "with-upstream": "true",
                "exclude": [upstream["own"].id],
            },
        )
        assert excluded.status_code == 202, excluded.json
        assert [run["automation"] for run in excluded.json["runs"]] == [downstream.id]
        assert {"automation": upstream["own"].id, "reason": "You left it out."} in (
            excluded.json["excluded"]
        )

        both = client.post(
            url, query_string={"with-upstream": "true", "with-downstream": "true"}
        )
        exclude_alone = client.post(url, query_string={"exclude": [upstream["own"].id]})
    assert both.status_code == 422, both.json
    assert exclude_alone.status_code == 422, exclude_alone.json


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_automation_with_downstream(
    app, fresh_db, upstream_automations, requesting_user
):
    """Triggering with downstream runs the automations waiting for this one, too, and lists the runs in chain order."""
    battery, sensor, upstream = upstream_automations
    upstream["own"].parameters = {"sensor": sensor.id}
    fresh_db.session.commit()
    with app.test_client() as client:
        created = _post(client, battery, sensor, [{"automation": upstream["own"].id}])
        assert created.status_code == 201, created.json
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=battery.id,
                automation_id=upstream["own"].id,
                **{"with-downstream": "true"},
            )
        )
    assert response.status_code == 202, response.json
    assert response.json["job"] is not None
    assert [
        (run["automation"], run["dispatch-state"]) for run in response.json["runs"]
    ] == [(upstream["own"].id, "queued"), (created.json["id"], "waiting")]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_automation_with_downstream_excludes_what_the_user_may_not_run(
    app, fresh_db, upstream_automations, requesting_user
):
    """Another organisation's automation waiting for this one does not run on the user's say, is not named, and does not keep the rest from running."""
    battery, sensor, upstream = upstream_automations
    upstream["own"].parameters = {"sensor": sensor.id}
    fresh_db.session.add(
        AutomationDependency(automation=upstream["foreign"], upstream=upstream["own"])
    )
    fresh_db.session.commit()
    with app.test_client() as client:
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=battery.id,
                automation_id=upstream["own"].id,
                **{"with-downstream": "true"},
            )
        )
    assert response.status_code == 202, response.json
    assert [run["automation"] for run in response.json["runs"]] == [upstream["own"].id]
    assert response.json["message"] == "Started 1 run."
    assert response.json["excluded"] == []
    runs = fresh_db.session.scalars(select(AutomationRun)).all()
    assert [run.automation_id for run in runs] == [upstream["own"].id]
