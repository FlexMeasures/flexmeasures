from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
)
from flexmeasures.utils.flexmeasures_inflection import humanize


class WeatherSensorType(db.Model):
    """
    This model is now considered legacy. See GenericAssetType.
    """

    name = db.Column(db.String(80), primary_key=True)
    display_name = db.Column(db.String(80), default="", unique=True)

    daily_seasonality = True
    weekly_seasonality = False
    yearly_seasonality = True

    def __init__(self, **kwargs):
        generic_asset_type = GenericAssetType(
            name=kwargs["name"], description=kwargs.get("hover_label", None)
        )
        db.session.add(generic_asset_type)
        super(WeatherSensorType, self).__init__(**kwargs)
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

    def __repr__(self):
        return "<WeatherSensorType %r>" % self.name
