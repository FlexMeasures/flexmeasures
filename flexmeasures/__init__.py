from importlib_metadata import version, PackageNotFoundError


__version__ = "Unknown"

# This uses importlib.metadata behaviour added in Python 3.8
# and relies on setuptools_scm.
try:
    __version__ = version("flexmeasures")
except PackageNotFoundError:
    # package is not installed
    pass
