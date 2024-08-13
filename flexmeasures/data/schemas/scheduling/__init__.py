from marshmallow import Schema, fields, validate

from flexmeasures.data.schemas.sensors import QuantityOrSensor, SensorIdField


class FlexContextSchema(Schema):
    """
    This schema lists fields that can be used to describe sensors in the optimised portfolio
    """

    # Energy commitments
    ems_power_capacity_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-power-capacity",
        validate=validate.Range(min=0),
    )
    consumption_price_sensor = SensorIdField(data_key="consumption-price-sensor")
    production_price_sensor = SensorIdField(data_key="production-price-sensor")

    # Capacity commitments
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
    ems_site_consumption_breach_price = fields.Float(
        data_key="site-consumption-breach-price", required=False, default=None
    )  # in EUR/MW
    ems_site_production_breach_price = fields.Float(
        data_key="site-production-breach-price", required=False, default=None
    )  # in EUR/MW

    # Peak consumption commitment
    ems_peak_consumption_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-peak-consumption",
        validate=validate.Range(min=0),
    )
    ems_peak_consumption_price = fields.Float(
        data_key="site-peak-consumption-price", required=False, default=None
    )  # in EUR/MW

    # Peak production commitment
    ems_peak_production_in_mw = QuantityOrSensor(
        "MW",
        required=False,
        data_key="site-peak-production",
        validate=validate.Range(min=0),
    )
    ems_peak_production_price = fields.Float(
        data_key="site-peak-production-price", required=False, default=None
    )  # in EUR/MW
    # todo: group by month start (MS), something like a commitment resolution, or a list of datetimes representing splits of the commitments

    inflexible_device_sensors = fields.List(
        SensorIdField(), data_key="inflexible-device-sensors"
    )
