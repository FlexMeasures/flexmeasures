from datetime import timedelta

from flexmeasures.data.services.generic_assets import format_json_field_change
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock


class NewAssetWithSensors:
    def __init__(self, db, setup_generic_asset_types, setup_accounts, setup_data):
        self.db = db
        self.setup_generic_asset_types = setup_generic_asset_types
        self.setup_accounts = setup_accounts
        self.setup_data = setup_data
        self.test_battery = None
        self.price_sensor1 = None
        self.price_sensor2 = None
        self.relationships = list()

    def __enter__(self):
        self.test_battery = GenericAsset(
            name="test battery",
            generic_asset_type=self.setup_generic_asset_types["battery"],
            owner=None,
            attributes={"some-attribute": "some-value", "sensors_to_show": [1, 2]},
        )
        self.db.session.add(self.test_battery)
        self.db.session.flush()

        for attribute_name, sensor_name in zip(
            ("price_sensor1", "price_sensor2"), ("sensor1", "sensor2")
        ):
            sensor = Sensor(
                name=sensor_name,
                generic_asset=self.test_battery,
                event_resolution=timedelta(hours=1),
                unit="EUR/MWh",
                knowledge_horizon=(
                    x_days_ago_at_y_oclock,
                    {"x": 1, "y": 12, "z": "Europe/Paris"},
                ),
                attributes=dict(
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=True,
                ),
            )
            setattr(self, attribute_name, sensor)
            self.db.session.add(sensor)
        self.db.session.flush()

        for attribute, sensor in zip(
            ("price_sensor1", "price_sensor2"), (self.price_sensor1, self.price_sensor2)
        ):
            if self.setup_data.get(attribute):
                if (
                    self.test_battery.flex_context.get("inflexible-device-sensors")
                    is None
                ):
                    self.test_battery.flex_context["inflexible-device-sensors"] = list()
                self.test_battery.flex_context["inflexible-device-sensors"].append(
                    sensor.id
                )
                self.db.session.add(self.test_battery)
        self.db.session.commit()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Delete sensors and test_battery
        for relationship in self.relationships:
            self.db.session.delete(relationship)
        self.db.session.commit()

        self.db.session.delete(self.price_sensor1)
        self.db.session.delete(self.price_sensor2)
        self.db.session.delete(self.test_battery)
        self.db.session.commit()


def test_format_json_field_change_reports_nested_flex_model_changes():
    old_value = {"soc-usage": ["3500 kW", {"sensor": 7}]}
    new_value = {"soc-usage": ["3500 kW", {"sensor": 8}]}

    change = format_json_field_change("flex_model", old_value, new_value)

    assert change == "Updated flex_model:\n1. Changed soc-usage[1].sensor: 7 → 8"


def test_format_json_field_change_handles_removed_middle_plot_without_false_replace():
    old_value = [
        {
            "title": "Storages SoC",
            "plots": [
                {"sensor": 1},
                {"sensor": 2, "flex-model": "soc-max"},
                {"sensor": 2, "flex-model": "soc-min"},
            ],
        }
    ]
    new_value = [
        {
            "title": "Storages SoC",
            "plots": [
                {"sensor": 1},
                {"sensor": 2, "flex-model": "soc-min"},
            ],
        }
    ]

    change = format_json_field_change("sensors_to_show", old_value, new_value)

    assert (
        change
        == "Updated sensors_to_show:\n1. Changed graph 1 (Storages SoC): removed plot 2"
    )


def test_format_json_field_change_does_not_duplicate_added_sensor_messages():
    old_value = [
        {
            "title": "Site capacity",
            "plots": [{"sensor": 10}, {"sensor": 11}],
        }
    ]
    new_value = [
        {
            "title": "Site capacity",
            "plots": [{"sensor": 10}, {"sensor": 11}, {"sensor": 46903}],
        }
    ]

    change = format_json_field_change("sensors_to_show", old_value, new_value)

    assert (
        change
        == 'Updated sensors_to_show:\n1. Changed graph 1 (Site capacity): added plot 3: {"sensor": 46903}'
    )
