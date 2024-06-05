from marshmallow import fields, pre_load, validate, validates_schema, Schema

from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import QuantityOrSensor, SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField
from flexmeasures.data.schemas.utils import FMValidationError


class FlexContextSchema(Schema):
    """This schema defines fields that provide context to the portfolio to be optimized."""

    ems_power_capacity_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-power-capacity",
        validate=validate.Range(min=0),
    )
    ems_production_capacity_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-production-capacity",
        validate=validate.Range(min=0),
    )
    ems_consumption_capacity_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-consumption-capacity",
        validate=validate.Range(min=0),
    )
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")
    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )


class SequentialFlexModelSchema(Schema):
    sensor = SensorIdField(required=True)
    sensor_flex_model = fields.Dict(data_key="sensor-flex-model")

    @pre_load
    def unwrap_envelope(self, data, **kwargs):
        """Any field other than 'sensor' becomes part of the sensor's flex-model."""
        extra = {}
        rest = {}
        for k, v in data.items():
            if k not in self.fields:
                extra[k] = v
            else:
                rest[k] = v
        return {"sensor-flex-model": extra, **rest}


class AssetTriggerSchema(Schema):
    asset = GenericAssetIdField(data_key="id")
    start_of_schedule = AwareDateTimeField(
        data_key="start", format="iso", required=True
    )
    belief_time = AwareDateTimeField(format="iso", data_key="prior")
    duration = PlanningDurationField(load_default=PlanningDurationField.load_default)
    flex_model = fields.List(
        fields.Nested(SequentialFlexModelSchema()),
        data_key="flex-model",
    )
    flex_context = fields.Dict(required=False, data_key="flex-context")

    @validates_schema
    def check_flex_model_sensors(self, data, **kwargs):
        """Verify that the flex-model's sensors live under the asset for which a schedule is triggered."""
        asset = data["asset"]
        sensors = []
        for sensor_flex_model in data["flex_model"]:
            sensor = sensor_flex_model["sensor"]
            if sensor in sensors:
                raise FMValidationError(
                    f"Sensor {sensor_flex_model['sensor'].id} should not occur more than once in the flex-model"
                )
            if sensor.generic_asset not in [asset] + asset.offspring:
                raise FMValidationError(
                    f"Sensor {sensor_flex_model['sensor'].id} does not belong to asset {asset.id} (or to one of its offspring)"
                )
            sensors.append(sensor)
        return data
