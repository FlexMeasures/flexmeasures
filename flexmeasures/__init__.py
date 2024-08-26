from importlib_metadata import version, PackageNotFoundError

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.user import (
    Account,
    AccountRole,
    User,
    Role as UserRole,
)
from flexmeasures.data.models.data_sources import DataSource as Source
from flexmeasures.data.models.generic_assets import (
    GenericAsset as Asset,
    GenericAssetType as AssetType,
)
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.time_series import Sensor


__version__ = "Unknown"

# This uses importlib.metadata behaviour added in Python 3.8
# and relies on setuptools_scm.
try:
    __version__ = version("flexmeasures")
except PackageNotFoundError:
    # package is not installed
    pass
