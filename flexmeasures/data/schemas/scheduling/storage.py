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

    soc_at_start = fields.Float(required=True, data_key="soc-at-start")
    soc_min = fields.Float(validate=validate.Range(min=0), data_key="soc-min")
    soc_max = fields.Float(data_key="soc-max")
    soc_unit = fields.Str(
        validate=OneOf(
            [
                "kWh",
                "MWh",
            ]
        ),
        data_key="soc-unit",
    )  # todo: allow unit to be set per field, using QuantityField("%", validate=validate.Range(min=0, max=1))
    soc_targets = fields.List(fields.Nested(SOCTargetSchema()), data_key="soc-targets")
    roundtrip_efficiency = QuantityField(
        "%", validate=validate.Range(min=0, max=1), data_key="roundtrip-efficiency"
    )
    prefer_charging_sooner = fields.Bool(data_key="prefer-charging-sooner")

    @post_load()
    def post_load_sequence(self, data: dict, **kwargs) -> dict:
        """Perform some checks and corrections after we loaded."""
        # currently we only handle MWh internally
        # TODO: review when we moved away from capacity having to be described in MWh
        if data.get("soc_unit") == "kWh":
            data["soc_at_start"] /= 1000.0
            if data.get("soc_min") is not None:
                data["soc_min"] /= 1000.0
            if data.get("soc_max") is not None:
                data["soc_max"] /= 1000.0
            if data.get("soc_targets"):
                for target in data["soc_targets"]:
                    target["value"] /= 1000.0

        # Convert round-trip efficiency to dimensionless (to the (0,1] range)
        if data.get("roundtrip_efficiency") is not None:
            data["roundtrip_efficiency"] = (
                data["roundtrip_efficiency"].to(ur.Quantity("dimensionless")).magnitude
            )

        return data
