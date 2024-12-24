from datetime import timedelta

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
