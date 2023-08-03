"""
Data schemas (Marshmallow)
"""

from .generic_assets import GenericAssetIdField as AssetIdField  # noqa F401
from .locations import LatitudeField, LongitudeField  # noqa F401
from .sensors import SensorIdField  # noqa F401
from .sources import DataSourceIdField as SourceIdField  # noqa F401
from .times import AwareDateTimeField, DurationField, TimeIntervalField  # noqa F401
