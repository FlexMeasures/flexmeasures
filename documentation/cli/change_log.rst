.. _cli-changelog:

**********************
FlexMeasures CLI Changelog
**********************

since v0.9.0 | March 25, 2022
==============================


* Add CLI commands for showing data ``flexmeasures show accounts``, ``flexmeasures show account``, ``flexmeasures show roles``, ``flexmeasures show asset-types``, ``flexmeasures show asset``, ``flexmeasures show data-sources``, and ``flexmeasures show beliefs``.
* Add ``flexmeasures db-ops resample-data`` CLI command to resample sensor data to a different resolution.
* Add ``flexmeasures edit attribute`` CLI command to edit/add an attribute on an asset or sensor.
* Add ``flexmeasures add toy-account`` for tutorials and trying things.
* Add ``flexmeasures add schedule`` to create a new schedule for a given power sensor.
* Add ``flexmeasures delete asset`` to delete an asset (including its sensors and data).
* Rename ``flexmeasures add structure`` to ``flexmeasures add initial-structure``. 


since v0.8.0 | January 26, 2022
===============================

* Add ``flexmeasures add sensor``, ``flexmeasures add asset-type``, ```flexmeasures add beliefs``. These were previously experimental features (under the `dev-add` command group).
* ``flexmeasures add asset`` now directly creates an asset in the new data model.
* Add ``flexmeasures delete sensor``, ``flexmeasures delete nan-beliefs`` and ``flexmeasures delete unchanged-beliefs``. 


since v0.6.0 | April 2, 2021
=====================

* Add ``flexmeasures add account``, ``flexmeasures delete account``, and the ``--account-id`` param to ``flexmeasures add user``.


since v0.4.0 | April 2, 2021
=====================

* Add the ``dev-add`` command group for experimental features around the upcoming data model refactoring.


since v0.3.0 | April 2, 2021
=====================

* Refactor CLI into the main groups ``add``, ``delete``, ``jobs`` and ``db-ops``
* Add ``flexmeasures add asset``,  ``flexmeasures add user`` and ``flexmeasures add weather-sensor``
* Split the ``populate-db`` command into ``flexmeasures add structure`` and ``flexmeasures add forecasts``
