# Requirements

All FlexMeasures requirements are specified in this directory.
We separate by use case:

- app: All requirements for running the FlexMeasures platform
- test: Additional requirements used for running automated tests 
- dev: Additional requirements used for developers (this includes testing)

Also note the following distinction:


## .in files

Here, we describe the requirements. We give the name of a requirement or even a range (e.g. `>=1.0.`).

## .txt files

These files are not to be edited by hand. They are created by `pip-compile` (or `make freeze-deps`).

Each requirement is pinned to a specific version in these files. The great benefit is reproducibility across environments (local dev as well as staging or production).

To update the .txt files for all supported Python versions, see `ci/update-packages.sh`.
