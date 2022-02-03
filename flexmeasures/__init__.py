from importlib_metadata import version, PackageNotFoundError

from flexmeasures.data.models.annotations import Annotation  # noqa F401
from flexmeasures.data.models.user import Account, AccountRole, User  # noqa F401
from flexmeasures.data.models.data_sources import DataSource as Source  # noqa F401
from flexmeasures.data.models.generic_assets import (  # noqa F401
    GenericAsset as Asset,
    GenericAssetType as AssetType,
)
from flexmeasures.data.models.time_series import Sensor  # noqa F401


__version__ = "Unknown"

# This uses importlib.metadata behaviour added in Python 3.8
# and relies on setuptools_scm.
try:
    __version__ = version("flexmeasures")
except PackageNotFoundError:
    # package is not installed
    pass
