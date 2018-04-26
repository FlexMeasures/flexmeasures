.. _config:

*****************************************************
Configuration variables
*****************************************************


Adding a configuration variable
-----------------------------------

A new configuration variable needs to be mentioned in `utils/config_defaults.py` in the `Config` class.
Think about if there is a useful default and also what defaults make sense in different environments (see subclasses of `Config`).
If no defaults make sense, simply use `None` as a value.

You then probably need to update config files that are in use, e.g. `Development-conf.py` (if you have used `None` in at least one environment).
The values for each environment are set in those files. Note that they might live on a server. Also note that they are not kep in git.