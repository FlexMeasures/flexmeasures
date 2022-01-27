.. _cli-changelog:

**********************
FlexMeasures CLI Changelog
**********************


since v0.9.0 | January 26, 2022
=====================

* add ``flexmeasures add sensor``, ''flexmeasures add generic-asset-type``, ``flexmeasures add generic-asset`` and ``flexmeasures add beliefs``. These were previously experimental features (under the `dev-add` command group).
* delete ``flexmeasures add asset``. Use ``flexmeasures add generic-asset`` instead.


since v0.6.0 | April 2, 2021
=====================

* add ``flexmeasures add account``, ``flexmeasures delete account``, and the ``--account-id`` param to ``flexmeasures add user``.


since v0.4.0 | April 2, 2021
=====================

* Add the ``dev-add`` command group for experimental features around the upcoming data model refactoring.


since v0.3.0 | April 2, 2021
=====================

* Refactor CLI into the main groups ``add``, ``delete``, ``jobs`` and ``db-ops``
* Add ``flexmeasures add asset``,  ``flexmeasures add user`` and ``flexmeasures add weather-sensor``
* split the ``populate-db`` command into ``flexmeasures add structure`` and ``flexmeasures add forecasts``
