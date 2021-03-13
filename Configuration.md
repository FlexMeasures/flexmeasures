# Configuration

FlexMeasures is best configured via a config file. We'll list all relevant settings in this document.
TODO: required settings can be set by env vars (for easier quickstart)
TODO: Required settings (e.g. postgres db) get a star, recommended settings (e.g. mail, redis) get a percent sign

The config file for FlexMeasures can be placed in one of two locations: 

* in the user's home directory (e.g. `~/.flexmeasures.cfg` on Unix). In this case, note the dot at the beginning of the filename!
* in the apps's instance directory (e.g. `/path/to/your/flexmeasures/code/instance/flexmeasures.cfg`). The path to that instance directory is shown to you by running flexmeasures (e.g. `flexmeasures run`) with required settings missing or otherwise by running `flexmeasures shell`.

TODO: For more details, dive in `flexmeasures/utils/config_defaults.py`. Might not be needed if we list all here.

## FlexMeasures

## Security

## SQLAlchemy

## Mail

## Redis



