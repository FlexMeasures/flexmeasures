import models.assets as asset

# Time resolutions
resolutions = ["15T", "1h", "1d", "1w"]

# The confidence interval for forecasting
confidence_interval_width = .9


class ModelException(Exception):
    pass
