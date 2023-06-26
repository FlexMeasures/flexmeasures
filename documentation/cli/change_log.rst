.. _cli-changelog:

**********************
FlexMeasures CLI Changelog
**********************

since v0.14.1 | June XX, 2023
=================================

* Avoid saving any :abbr:`NaN (not a number)` values to the database, when calling ``flexmeasures add report``.
* Fix defaults for the ``--start-offset`` and ``--end-offset` options to ``flexmeasures add report``, which weren't being interpreted in the local timezone of the reporting sensor.

since v0.14.0 | June 15, 2023
=================================

* Allow setting a storage efficiency using the new ``--storage-efficiency`` option to the ``flexmeasures add schedule for-storage`` CLI command.
* Add CLI command ``flexmeasures add report`` to calculate a custom report from sensor data and save the results to the database, with the option to export them to a CSV or Excel file.
* Add CLI command ``flexmeasures show reporters`` to list available reporters, including any defined in registered plugins.
* Add CLI command ``flexmeasures show schedulers`` to list available schedulers, including any defined in registered plugins.
* Make ``--account-id`` optional in ``flexmeasures add asset`` to support creating public assets, which are available to all users.

since v0.13.0 | May 1, 2023
=================================

* Add ``flexmeasures add source`` CLI command for adding a new data source.
* Add ``--inflexible-device-sensor`` option to ``flexmeasures add schedule``.

since v0.12.0 | January 04, 2023
=================================

* Add ``--resolution``, ``--timezone`` and ``--to-file`` options to ``flexmeasures show beliefs``, to show beliefs data in a custom resolution and/or timezone, and also to save shown beliefs data to a CSV file.
* Add options to ``flexmeasures add beliefs`` to 1) read CSV data with timezone naive datetimes (use ``--timezone`` to localize the data), 2) read CSV data with datetime/timedelta units (use ``--unit datetime`` or ``--unit timedelta``, 3) remove rows with NaN values, and 4) add filter to read-in data by matching values in specific columns (use ``--filter-column`` and ``--filter-value`` together).
* Fix ``flexmeasures db-ops dump`` and ``flexmeasures db-ops restore`` incorrectly reporting a success when `pg_dump` and `pg_restore` are not installed.
* Add ``flexmeasures monitor last-seen``. 
* Rename ``flexmeasures monitor tasks`` to ``flexmeasures monitor last-run``. 
* Rename ``flexmeasures add schedule`` to ``flexmeasures add schedule for-storage`` (in expectation of more scheduling commands, based on in-built flex models). 


since v0.11.0 | August 28, 2022
==============================

* Add ``flexmeasures jobs show-queues`` to show contents of computation job queues.
* ``--name`` parameter in ``flexmeasures jobs run-worker`` is now optional.
* Add ``--custom-message`` param to ``flexmeasures monitor tasks``.
* Rename ``-optimization-context-id`` to ``--consumption-price-sensor`` in ``flexmeasures add schedule``, and added ``--production-price-sensor``.


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
