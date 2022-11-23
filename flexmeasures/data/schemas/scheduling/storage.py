from marshmallow import Schema, post_load, validate, fields
from marshmallow.validate import OneOf

from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.utils.unit_utils import ur


class SOCTargetSchema(Schema):
    """
    A point in time with a target value.

    Target SOC values should be indexed by their due date. For example, for quarter-hourly targets between 5 and 6 AM:
    >>> df = pd.Series(data=[1, 2, 2.5, 3], index=pd.date_range(datetime(2010,1,1,5), datetime(2010,1,1,6), freq=timedelta(minutes=15), inclusive="right"))
    >>> print(df)
        2010-01-01 05:15:00    1.0
        2010-01-01 05:30:00    2.0
        2010-01-01 05:45:00    2.5
        2010-01-01 06:00:00    3.0
        Freq: 15T, dtype: float64

    """

    value = fields.Float(required=True)
    datetime = AwareDateTimeField(required=True)


class StorageFlexModelSchema(Schema):
    """
    This schema lists fields we require when scheduling storage assets.
    Some fields are not required, as they might live on the Sensor.attributes.
    You can use StorageScheduler.ensure_flex_model to get that filled in.
    """

    soc_at_start = fields.Float(required=True)
    soc_min = fields.Float()
    soc_max = fields.Float()
    soc_unit = fields.Str(
        validate=OneOf(
            [
                "kWh",
                "MWh",
            ]
        ),
    )  # todo: allow unit to be set per field, using QuantityField("%", validate=validate.Range(min=0, max=1))
    soc_targets = fields.List(fields.Nested(SOCTargetSchema()))
    roundtrip_efficiency = QuantityField(
        "%",
        validate=validate.Range(min=0, max=1),
    )
    prefer_charging_sooner = fields.Bool()

    @post_load()
    def post_load_sequence(self, data: dict, **kwargs) -> dict:
        """Perform some checks and corrections after we loaded."""
        # currently we only handle MWh internally
        # TODO: review when we moved away from capacity having to be described in MWh
        if data.get("soc_unit") == "kWh":
            data["soc_at_start"] = data["soc_at_start"] / 1000.0
            if data.get("soc_min") is not None:
                data["soc_min"] = data["soc_min"] / 1000.0
            if data.get("soc_max") is not None:
                data["soc_max"] = data["soc_max"] / 1000.0

        # Convert round-trip efficiency to dimensionless (to the (0,1] range)
        if data.get("roundtrip_efficiency") is not None:
            data["roundtrip_efficiency"] = (
                data["roundtrip_efficiency"].to(ur.Quantity("dimensionless")).magnitude
            )

        # TODO: Can this TODO go after we deprecated API versions <=2? I saw it happening in v1.3
        # TODO: if a soc-sensor entity address is passed, persist those values to the corresponding sensor
        #       (also update the note in posting_data.rst about flexibility states not being persisted).

        return data
