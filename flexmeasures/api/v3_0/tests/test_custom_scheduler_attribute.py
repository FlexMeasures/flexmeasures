"""The custom-scheduler attribute may only name a registered scheduler.

Asset and sensor attributes are editable by account members,
so a module or file path in that attribute must never be imported or executed,
not when a schedule is triggered.
"""

from __future__ import annotations

import sys

import pytest
from flask import url_for

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.services.scheduling import find_scheduler_class

PLANTED_CLASS = "PlantedScheduler"


@pytest.fixture
def planted_module(tmp_path):
    """A Python file that leaves a marker file behind when it is executed, and the marker's path."""
    marker = tmp_path / "executed"
    module = tmp_path / "planted.py"
    module.write_text(
        f"open({str(marker)!r}, 'w').close()\n"
        f"class {PLANTED_CLASS}:\n"
        "    def compute(self):\n"
        "        return []\n"
    )
    yield {"module": str(module), "class": PLANTED_CLASS}, marker
    sys.modules.pop(PLANTED_CLASS, None)


@pytest.fixture
def battery(db, add_battery_assets):
    """The test battery, with its custom-scheduler attributes removed again afterwards."""
    battery = add_battery_assets["Test battery"]
    yield battery
    battery.attributes.pop("custom-scheduler", None)
    battery.sensors[0].attributes.pop("custom-scheduler", None)
    db.session.commit()


def _set_custom_scheduler(db, asset_or_sensor, specs):
    asset_or_sensor.attributes = {
        **asset_or_sensor.attributes,
        "custom-scheduler": specs,
    }
    db.session.commit()


def test_a_registered_scheduler_name_is_still_found(app, db, battery):
    _set_custom_scheduler(db, battery, "StorageScheduler")
    assert find_scheduler_class(battery) is StorageScheduler


def test_a_module_path_in_the_attribute_is_refused_unexecuted(
    app, db, battery, planted_module
):
    specs, marker = planted_module
    _set_custom_scheduler(db, battery, specs)
    with pytest.raises(ValueError, match="registered scheduler"):
        find_scheduler_class(battery)
    assert not marker.exists()
    assert PLANTED_CLASS not in sys.modules


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_triggering_a_schedule_does_not_run_a_module_named_in_attributes(
    app,
    db,
    add_market_prices,
    battery,
    battery_soc_sensor,
    keep_scheduling_queue_empty,
    requesting_user,
    planted_module,
):
    specs, marker = planted_module
    sensor = battery.sensors[0]
    _set_custom_scheduler(db, sensor, specs)

    with app.test_client() as client:
        response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message_for_trigger_schedule(),
        )

    assert response.status_code in (400, 422), response.json
    assert not marker.exists()
    assert PLANTED_CLASS not in sys.modules
