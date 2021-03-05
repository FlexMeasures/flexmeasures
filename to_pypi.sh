#!/bin/bash


# Script to release FlexMeasures to Pypi
#
# The version comes from setuptools_scm. See `python setup.py --version`.
#
# This version includes a .devN identifier, where N is the number of commits since the last version tag.
#
# Note that the only way to create a new dev release is to add another commit on your development branch.
#
# Let's explore the topic of dev releases: 
# We've disabled setuptools_scm's ability to add a local scheme (git commit and date), as that
# isn't formatted in a way that Pypi accepts it.
# 
# We can not add a local version identifier ("+N") which is allowed in PEP 440 but explicitly disallowed by Pypi.
# 
# If we'd add a number to .devN (.devNN), the ordering of dev versions would be disturbed after the next local commit.
# 
# So we'll use these tools as the experts intend us to.
#
# If you want, you can read more about acceptable versions in PEP 440: https://www.python.org/dev/peps/pep-0440/


rm -rf build/* dist/*
pip -q install twine

python setup.py egg_info sdist
python setup.py egg_info bdist_wheel

twine upload dist/*