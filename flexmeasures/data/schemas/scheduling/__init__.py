from marshmallow import Schema, fields, validate

from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import QuantityOrSensor, SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, PlanningDurationField


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


class AssetTriggerSchema(Schema):
    asset = GenericAssetIdField(data_key="id", status_if_not_found=404)
    start_of_schedule = AwareDateTimeField(
        data_key="start", format="iso", required=True
    )
    belief_time = AwareDateTimeField(format="iso", data_key="prior")
    duration = PlanningDurationField(
        load_default=PlanningDurationField.load_default
    )
    flex_model = fields.Dict(data_key="flex-model")
    flex_context = fields.Dict(required=False, data_key="flex-context")
