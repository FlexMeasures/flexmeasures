#!/bin/bash


# Script to release FlexMeasures to PyPi.
#
# Cleans up build and dist dirs, checks for python files which are not in git, installs dependencies
# and finally uploads tar and wheel packages to Pypi.
#
#
# Usage
# ------------
#
# ./to_pypi [--dry-run]
#
# If the --dry-run flag is present, this script will do all steps, but skip the upload to Pypi.
# 
#
# The version
# -------------
# The version comes from setuptools_scm. See `python setup.py --version`.
# setuptools_scm works via git tags that should implement a semantic versioning scheme, e.g. v0.2.3
#
# If there were zero commits since the most recent tag, we have a real release and the version basically *is* what the tag says.
# Otherwise, the version also includes a .devN identifier, where N is the number of commits since the last version tag.
#
# More information on creating a dev release
# -------------------------------------------
# Note that the only way to create a new dev release is to add another commit on your development branch.
# It might have been convenient to not have to commit to do that (for experimenting with very small changes),
# but we decided against that. Let's explore why for a bit:
#
# First, setuptools_scm has the ability to add a local scheme (git commit and date/time) to the version,
# but we've disabled that, as that extra part isn't formatted in a way that Pypi accepts it.
# Another way would have been to add a local version identifier ("+M", note the plus sign),
# which is allowed in PEP 440 but explicitly disallowed by Pypi.
# Finally, if we simply add a number to .devN (-> .devNM), the ordering of dev versions would be
# disturbed after the next local commit (e.g. we add 1 to .dev4, making it .dev41, and then the next version, .dev5,
# is not the highest version chosen by PyPi).
# 
# So we'll use these tools as the experts intended.
# If you want, you can read more about acceptable versions in PEP 440: https://www.python.org/dev/peps/pep-0440/


NUM_PY_FILES_IN_FM=$(git status --porcelain flexmeasures | grep '??.*\.py' | wc -l)
if [ $NUM_PY_FILES_IN_FM -gt 0 ]; then
    PY_FILES_IN_FM=$(git status --porcelain flexmeasures | grep '??.*\.py')
    echo """[TO_PYPI] The following python files are not under git control but would be packaged anyways (unless explicitly excluded, e.g. in MANIFEST.in):

$PY_FILES_IN_FM

You probably want to remove any files with sensitive data; or add a MANIFEST.in file with 'exclude flexmeasures/path/to/filename' ...
    """
    read -p "Continue (y/n)? " choice
    case "$choice" in 
        y|Y ) echo "If you say so. Continuing ...";;
        n|N ) echo "Aborting ..."; exit 2;;
        * ) echo "invalid choice";;
    esac
fi

echo "[TO_PYPI] Cleaning ..."
rm -rf build/* dist/*

echo "[TO_PYPI] Installing dependencies ..."
pip -q install twine
pip -q install wheel

echo "[TO_PYPI] Packaging ..."
python setup.py egg_info sdist
python setup.py egg_info bdist_wheel

if [ "$1" == "--dry-run" ]; then
    echo "[TO_PYPI] Not uploading to Pypi (--dry-run active) ..."
    exit
fi
echo "[TO_PYPI] Uploading to Pypi ..."
twine upload dist/*
