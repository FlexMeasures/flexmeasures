
**********************
FlexMeasures Changelog
**********************

v0.14.2 | July 25, 2023
============================

Bugfixes
-----------

* The error handling for infeasible constraints in storage.py was given too many arguments. This caused the response from the API to be unhelpful when a schedule was requested with infeasible constraints. [see `PR #758 <https://github.com/FlexMeasures/flexmeasures/pull/758>`_]


v0.14.1 | June 26, 2023
============================

Bugfixes
-----------

* Relax constraint validation of `StorageScheduler` to accommodate violations caused by floating point precision [see `PR #731 <https://www.github.com/FlexMeasures/flexmeasures/pull/731>`_]
* Avoid saving any :abbr:`NaN (not a number)` values to the database, when calling ``flexmeasures add report`` [see `PR #735 <https://www.github.com/FlexMeasures/flexmeasures/pull/735>`_]
* Fix browser console error when loading asset or sensor page with only a single data point [see `PR #732 <https://www.github.com/FlexMeasures/flexmeasures/pull/732>`_]
* Fix showing multiple sensors with bare 3-letter currency code as their units (e.g. EUR) in one chart [see `PR #738 <https://www.github.com/FlexMeasures/flexmeasures/pull/738>`_]
* Fix defaults for the ``--start-offset`` and ``--end-offset`` options to ``flexmeasures add report``, which weren't being interpreted in the local timezone of the reporting sensor [see `PR #744 <https://www.github.com/FlexMeasures/flexmeasures/pull/744>`_]
* Relax constraint for overlaying plot traces for sensors with various resolutions, making it possible to show e.g. two price sensors in one chart, where one of them records hourly prices and the other records quarter-hourly prices [see `PR #743 <https://www.github.com/FlexMeasures/flexmeasures/pull/743>`_]
* Resolve bug where different page loads would potentially influence the time axis of each other's charts, by avoiding mutation of shared field definitions [see `PR #746 <https://www.github.com/FlexMeasures/flexmeasures/pull/746>`_]


v0.14.0 | June 15, 2023
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/014-reporting-power/>`__.

New features
-------------

* Allow setting a storage efficiency using the new ``storage-efficiency`` field when calling `/sensors/<id>/schedules/trigger` (POST) through the API (within the ``flex-model`` field), or when calling ``flexmeasures add schedule for-storage`` through the CLI [see `PR #679 <https://www.github.com/FlexMeasures/flexmeasures/pull/679>`_]
* Allow setting multiple :abbr:`SoC (state of charge)` maxima and minima constraints for the `StorageScheduler`, using the new ``soc-minima`` and ``soc-maxima`` fields when calling `/sensors/<id>/schedules/trigger` (POST) through the API (within the ``flex-model`` field) [see `PR #680 <https://www.github.com/FlexMeasures/flexmeasures/pull/680>`_]
* New CLI command ``flexmeasures add report`` to calculate a custom report from sensor data and save the results to the database, with the option to export them to a CSV or Excel file [see `PR #659 <https://www.github.com/FlexMeasures/flexmeasures/pull/659>`_]
* New CLI commands ``flexmeasures show reporters`` and ``flexmeasures show schedulers`` to list available reporters and schedulers, respectively, including any defined in registered plugins [see `PR #686 <https://www.github.com/FlexMeasures/flexmeasures/pull/686>`_ and `PR #708 <https://github.com/FlexMeasures/flexmeasures/pull/708>`_]
* Allow creating public assets through the CLI, which are available to all users [see `PR #727 <https://github.com/FlexMeasures/flexmeasures/pull/727>`_]

Bugfixes
-----------
* Fix charts not always loading over https in secured scenarios [see `PR #716 <https://www.github.com/FlexMeasures/flexmeasures/pull/716>`_]

Infrastructure / Support
----------------------

* Introduction of the classes `Reporter`, `PandasReporter` and `AggregatorReporter` to help customize your own reporter functions (experimental) [see `PR #641 <https://www.github.com/FlexMeasures/flexmeasures/pull/641>`_ and `PR #712 <https://www.github.com/FlexMeasures/flexmeasures/pull/712>`_]
* The setting FLEXMEASURES_PLUGINS can be set as environment variable now (as a comma-separated list) [see `PR #660 <https://www.github.com/FlexMeasures/flexmeasures/pull/660>`_]
* Packaging was modernized to stop calling setup.py directly [see `PR #671 <https://www.github.com/FlexMeasures/flexmeasures/pull/671>`_]
* Remove API versions 1.0, 1.1, 1.2, 1.3 and 2.0, while making sure that sunset endpoints keep returning ``HTTP status 410 (Gone)`` responses [see `PR #667 <https://www.github.com/FlexMeasures/flexmeasures/pull/667>`_ and `PR #717 <https://www.github.com/FlexMeasures/flexmeasures/pull/717>`_]
* Support Pandas 2 [see `PR #673 <https://www.github.com/FlexMeasures/flexmeasures/pull/673>`_]
* Add code documentation from package structure and docstrings to official docs [see `PR #698 <https://www.github.com/FlexMeasures/flexmeasures/pull/698>`_]

.. warning:: The setting `FLEXMEASURES_PLUGIN_PATHS` has been deprecated since v0.7. It has now been sunset. Please replace it with :ref:`plugin-config`.


v0.13.3 | June 10, 2023
=======================

Bugfixes
---------
* Fix forwarding arguments in deprecated util function [see `PR #719 <https://github.com/FlexMeasures/flexmeasures/pull/719>`_]


v0.13.2 | June 9, 2023
=======================

Bugfixes
---------
* Fix failing to save results of scheduling and reporting on subsequent calls for the same time period [see `PR #709 <https://github.com/FlexMeasures/flexmeasures/pull/709>`_]


v0.13.1 | May 12, 2023
=======================

Bugfixes
---------
* `@deprecated` not returning the output of the decorated function [see `PR #678 <https://www.github.com/FlexMeasures/flexmeasures/pull/678>`_]


v0.13.0 | May 1, 2023
============================

.. warning:: Sunset notice for API versions 1.0, 1.1, 1.2, 1.3 and 2.0: after upgrading to ``flexmeasures==0.13``, users of these API versions may receive ``HTTP status 410 (Gone)`` responses.
             See the `documentation for deprecation and sunset <https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset>`_.
             The relevant endpoints have been deprecated since ``flexmeasures==0.12``.

.. warning:: The API endpoint (`[POST] /sensors/(id)/schedules/trigger <api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_) to make new schedules sunsets the deprecated (since v0.12) storage flexibility parameters (they move to the ``flex-model`` parameter group), as well as the parameters describing other sensors (they move to ``flex-context``).

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/013-overlay-charts/>`__.

New features
-------------
* Keyboard control over replay [see `PR #562 <https://www.github.com/FlexMeasures/flexmeasures/pull/562>`_]
* Overlay charts (e.g. power profiles) on the asset page using the `sensors_to_show` attribute, and distinguish plots by source (different trace), sensor (different color) and source type (different stroke dash) [see `PR #534 <https://www.github.com/FlexMeasures/flexmeasures/pull/534>`_]
* The ``FLEXMEASURES_MAX_PLANNING_HORIZON`` config setting can also be set as an integer number of planning steps rather than just as a fixed duration, which makes it possible to schedule further ahead in coarser time steps [see `PR #583 <https://www.github.com/FlexMeasures/flexmeasures/pull/583>`_]
* Different text styles for CLI output for errors, warnings or success messages. [see `PR #609 <https://www.github.com/FlexMeasures/flexmeasures/pull/609>`_]
* Added API endpoints and webpages `/accounts` and `/accounts/<id>` to list accounts and show an overview of the assets, users and account roles of an account [see `PR #605 <https://github.com/FlexMeasures/flexmeasures/pull/605>`_]
* Avoid redundantly recomputing jobs that are triggered without a relevant state change. `FLEXMEASURES_JOB_CACHE_TTL` config setting defines the time in which the jobs with the same arguments are not being recomputed. [see `PR #616 <https://www.github.com/FlexMeasures/flexmeasures/pull/616>`_]

Bugfixes
-----------

* Fix copy button on tutorials and other documentation, so that only commands are copied and no output or comments [see `PR #636 <https://www.github.com/FlexMeasures/flexmeasures/pull/636>`_]
* GET /api/v3_0/assets/public should ask for token authentication and not forward to login page [see `PR #649 <https://www.github.com/FlexMeasures/flexmeasures/pull/649>`_]

Infrastructure / Support
----------------------
* Support blackout tests for sunset API versions [see `PR #651 <https://www.github.com/FlexMeasures/flexmeasures/pull/651>`_]
* Sunset API versions 1.0, 1.1, 1.2, 1.3 and 2.0 [see `PR #650 <https://www.github.com/FlexMeasures/flexmeasures/pull/650>`_]
* Sunset several API fields for `/sensors/<id>/schedules/trigger` (POST) that have moved into the ``flex-model`` or ``flex-context`` fields [see `PR #580 <https://www.github.com/FlexMeasures/flexmeasures/pull/580>`_]
* Fix broken `make show-data-model` command [see `PR #638 <https://www.github.com/FlexMeasures/flexmeasures/pull/638>`_]
* Bash script for a clean database to run toy-tutorial by using `make clean-db db_name=database_name` command [see `PR #640 <https://github.com/FlexMeasures/flexmeasures/pull/640>`_]


v0.12.3 | February 28, 2023
============================

Bugfixes
-----------

- Fix premature deserialization of ``flex-context`` field for `/sensors/<id>/schedules/trigger` (POST) [see `PR #593 <https://www.github.com/FlexMeasures/flexmeasures/pull/593>`_]


v0.12.2 | February 4, 2023
============================

Bugfixes
-----------
* Fix CLI command ``flexmeasures schedule for-storage`` without ``--as-job`` flag [see `PR #589 <https://www.github.com/FlexMeasures/flexmeasures/pull/589>`_]


v0.12.1 | January 12, 2023
============================

Bugfixes
-----------
* Fix validation of (deprecated) API parameter ``roundtrip-efficiency`` [see `PR #582 <https://www.github.com/FlexMeasures/flexmeasures/pull/582>`_]


v0.12.0 | January 4, 2023
============================

.. warning:: After upgrading to ``flexmeasures==0.12``, users of API versions 1.0, 1.1, 1.2, 1.3 and 2.0 will receive ``"Deprecation"`` and ``"Sunset"`` response headers, and warnings are logged for FlexMeasures hosts whenever users call API endpoints in these deprecated API versions.
             The relevant endpoints are planned to become unresponsive in ``flexmeasures==0.13``.

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/012-replay-custom-scheduling/>`__.

New features
-------------

* Hit the replay button to visually replay what happened, available on the sensor and asset pages [see `PR #463 <https://www.github.com/FlexMeasures/flexmeasures/pull/463>`_ and `PR #560 <https://www.github.com/FlexMeasures/flexmeasures/pull/560>`_]
* Ability to provide your own custom scheduling function [see `PR #505 <https://www.github.com/FlexMeasures/flexmeasures/pull/505>`_]
* Visually distinguish forecasts/schedules (dashed lines) from measurements (solid lines), and expand the tooltip with timing info regarding the forecast/schedule horizon or measurement lag [see `PR #503 <https://www.github.com/FlexMeasures/flexmeasures/pull/503>`_]
* The asset page also allows to show sensor data from other assets that belong to the same account [see `PR #500 <https://www.github.com/FlexMeasures/flexmeasures/pull/500>`_]
* The CLI command ``flexmeasures monitor latest-login`` supports to check if (bot) users who are expected to contact FlexMeasures regularly (e.g. to send data) fail to do so [see `PR #541 <https://www.github.com/FlexMeasures/flexmeasures/pull/541>`_]
* The CLI command ``flexmeasures show beliefs`` supports showing beliefs data in a custom resolution and/or timezone, and also saving the shown beliefs data to a CSV file [see `PR #519 <https://www.github.com/FlexMeasures/flexmeasures/pull/519>`_]
* Improved import of time series data from CSV file: 1) drop duplicate records with warning, 2) allow configuring which column contains explicit recording times for each data point (use case: import forecasts) [see `PR #501 <https://www.github.com/FlexMeasures/flexmeasures/pull/501>`_], 3) localize timezone naive data, 4) support reading in datetime and timedelta values, 5) remove rows with NaN values, and 6) filter by values in specific columns [see `PR #521 <https://www.github.com/FlexMeasures/flexmeasures/pull/521>`_]
* Filter data by source in the API endpoint `/sensors/data` (GET) [see `PR #543 <https://www.github.com/FlexMeasures/flexmeasures/pull/543>`_]
* Allow posting ``null`` values to `/sensors/data` (POST) to correctly space time series that include missing values (the missing values are not stored) [see `PR #549 <https://www.github.com/FlexMeasures/flexmeasures/pull/549>`_]
* Allow setting a custom planning horizon when calling `/sensors/<id>/schedules/trigger` (POST), using the new ``duration`` field [see `PR #568 <https://www.github.com/FlexMeasures/flexmeasures/pull/568>`_]
* New resampling functionality for instantaneous sensor data: 1) ``flexmeasures show beliefs`` can now handle showing (and saving) instantaneous sensor data and non-instantaneous sensor data together, and 2) the API endpoint `/sensors/data` (GET) now allows fetching instantaneous sensor data in a custom frequency, by using the "resolution" field [see `PR #542 <https://www.github.com/FlexMeasures/flexmeasures/pull/542>`_]

Bugfixes
-----------
* The CLI command ``flexmeasures show beliefs`` now supports plotting time series data that includes NaN values, and provides better support for plotting multiple sensors that do not share the same unit [see `PR #516 <https://www.github.com/FlexMeasures/flexmeasures/pull/516>`_ and `PR #539 <https://www.github.com/FlexMeasures/flexmeasures/pull/539>`_]
* Fixed JSON wrapping of return message for `/sensors/data` (GET) [see `PR #543 <https://www.github.com/FlexMeasures/flexmeasures/pull/543>`_]
* Consistent CLI/UI support for asset lat/lng positions up to 7 decimal places (previously the UI rounded to 4 decimal places, whereas the CLI allowed more than 4) [see `PR #522 <https://www.github.com/FlexMeasures/flexmeasures/pull/522>`_]
* Stop trimming the planning window in response to price availability, which is a problem when :abbr:`SoC (state of charge)` targets occur outside of the available price window, by making a simplistic assumption about future prices [see `PR #538 <https://www.github.com/FlexMeasures/flexmeasures/pull/538>`_]
* Faster loading of initial charts and calendar date selection [see `PR #533 <https://www.github.com/FlexMeasures/flexmeasures/pull/533>`_]

Infrastructure / Support
----------------------

* Reduce size of Docker image (from 2GB to 1.4GB) [see `PR #512 <https://www.github.com/FlexMeasures/flexmeasures/pull/512>`_]
* Allow extra requirements to be freshly installed when running ``docker-compose up`` [see `PR #528 <https://www.github.com/FlexMeasures/flexmeasures/pull/528>`_]
* Remove bokeh dependency and obsolete UI views [see `PR #476 <https://www.github.com/FlexMeasures/flexmeasures/pull/476>`_]
* Fix ``flexmeasures db-ops dump`` and ``flexmeasures db-ops restore`` not working in docker containers [see `PR #530 <https://www.github.com/FlexMeasures/flexmeasures/pull/530>`_] and incorrectly reporting a success when `pg_dump` and `pg_restore` are not installed [see `PR #526 <https://www.github.com/FlexMeasures/flexmeasures/pull/526>`_]
* Plugins can save BeliefsSeries, too, instead of just BeliefsDataFrames [see `PR #523 <https://www.github.com/FlexMeasures/flexmeasures/pull/523>`_]
* Improve documentation and code w.r.t. storage flexibility modelling ― prepare for handling other schedulers & merge battery and car charging schedulers [see `PR #511 <https://www.github.com/FlexMeasures/flexmeasures/pull/511>`_, `PR #537 <https://www.github.com/FlexMeasures/flexmeasures/pull/537>`_ and `PR #566 <https://www.github.com/FlexMeasures/flexmeasures/pull/566>`_]
* Revised strategy for removing unchanged beliefs when saving data: retain the oldest measurement (ex-post belief), too [see `PR #518 <https://www.github.com/FlexMeasures/flexmeasures/pull/518>`_]
* Scheduling test for maximizing self-consumption, and improved time series db queries for fixed tariffs (and other long-term constants) [see `PR #532 <https://www.github.com/FlexMeasures/flexmeasures/pull/532>`_]
* Clean up table formatting for ``flexmeasures show`` CLI commands [see `PR #540 <https://www.github.com/FlexMeasures/flexmeasures/pull/540>`_]
* Add  ``"Deprecation"`` and ``"Sunset"`` response headers for API users of deprecated API versions, and log warnings for FlexMeasures hosts when users still use them [see `PR #554 <https://www.github.com/FlexMeasures/flexmeasures/pull/554>`_ and `PR #565 <https://www.github.com/FlexMeasures/flexmeasures/pull/565>`_]
* Explain how to avoid potential ``SMTPRecipientsRefused`` errors when using FlexMeasures in combination with a mail server [see `PR #558 <https://www.github.com/FlexMeasures/flexmeasures/pull/558>`_]
* Set a limit to the allowed planning window for API users, using the ``FLEXMEASURES_MAX_PLANNING_HORIZON`` setting [see `PR #568 <https://www.github.com/FlexMeasures/flexmeasures/pull/568>`_]

.. warning:: The API endpoint (`[POST] /sensors/(id)/schedules/trigger <api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_) to make new schedules will (in v0.13) sunset the storage flexibility parameters (they move to the ``flex-model`` parameter group), as well as the parameters describing other sensors (they move to ``flex-context``).

.. warning:: The CLI command ``flexmeasures monitor tasks`` has been  deprecated (it's being renamed to ``flexmeasures monitor last-run``). The old name will be sunset in version 0.13.
    
.. warning:: The CLI command  ``flexmeasures add schedule`` has been renamed to ``flexmeasures add schedule for-storage``. The old name will be sunset in version 0.13.


v0.11.3 | November 2, 2022
============================

Bugfixes
-----------
* Fix scheduling with imperfect efficiencies, which resulted in exceeding the device's lower :abbr:`SoC (state of charge)` limit. [see `PR #520 <https://www.github.com/FlexMeasures/flexmeasures/pull/520>`_]
* Fix scheduler for Charge Points when taking into account inflexible devices [see `PR #517 <https://www.github.com/FlexMeasures/flexmeasures/pull/517>`_]
* Prevent rounding asset lat/long positions to 4 decimal places when editing an asset in the UI [see `PR #522 <https://www.github.com/FlexMeasures/flexmeasures/pull/522>`_]


v0.11.2 | September 6, 2022
============================

Bugfixes
-----------
* Fix regression for sensors recording non-instantaneous values [see `PR #498 <https://www.github.com/FlexMeasures/flexmeasures/pull/498>`_]
* Fix broken auth check for creating assets with CLI [see `PR #497 <https://www.github.com/FlexMeasures/flexmeasures/pull/497>`_]


v0.11.1 | September 5, 2022
============================

Bugfixes
-----------
* Do not fail asset page if none of the sensors has any data [see `PR #493 <https://www.github.com/FlexMeasures/flexmeasures/pull/493>`_]
* Do not fail asset page if one of the shown sensors records instantaneous values [see `PR #491 <https://www.github.com/FlexMeasures/flexmeasures/pull/491>`_]


v0.11.0 | August 28, 2022
===========================

New features
-------------
* The asset page now shows the most relevant sensor data for the asset [see `PR #449 <https://www.github.com/FlexMeasures/flexmeasures/pull/449>`_]
* Individual sensor charts show available annotations [see `PR #428 <https://www.github.com/FlexMeasures/flexmeasures/pull/428>`_]
* New API options to further customize the optimization context for scheduling, including the ability to use different prices for consumption and production (feed-in) [see `PR #451 <https://www.github.com/FlexMeasures/flexmeasures/pull/451>`_]
* Admins can group assets by account on dashboard & assets page [see `PR #461 <https://www.github.com/FlexMeasures/flexmeasures/pull/461>`_]
* Collapsible side-panel (hover/swipe) used for date selection on sensor charts, and various styling improvements [see `PR #447 <https://www.github.com/FlexMeasures/flexmeasures/pull/447>`_ and `PR #448 <https://www.github.com/FlexMeasures/flexmeasures/pull/448>`_]
* Add CLI command ``flexmeasures jobs show-queues`` [see `PR #455 <https://www.github.com/FlexMeasures/flexmeasures/pull/455>`_]
* Switched from 12-hour AM/PM to 24-hour clock notation for time series chart axis labels [see `PR #446 <https://www.github.com/FlexMeasures/flexmeasures/pull/446>`_]
* Get data in a given resolution [see `PR #458 <https://www.github.com/FlexMeasures/flexmeasures/pull/458>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/011-better-data-views/>`__.

Bugfixes
-----------
* Do not fail asset page if entity addresses cannot be built [see `PR #457 <https://www.github.com/FlexMeasures/flexmeasures/pull/457>`_]
* Asynchronous reloading of a chart's dataset relies on that chart already having been embedded [see `PR #472 <https://www.github.com/FlexMeasures/flexmeasures/pull/472>`_]
* Time scale axes in sensor data charts now match the requested date range, rather than stopping at the edge of the available data [see `PR #449 <https://www.github.com/FlexMeasures/flexmeasures/pull/449>`_]
* The docker-based tutorial now works with UI on all platforms (port 5000 did not expose on MacOS) [see `PR #465 <https://www.github.com/FlexMeasures/flexmeasures/pull/465>`_]
* Fix interpretation of scheduling results in toy tutorial [see `PR #466 <https://www.github.com/FlexMeasures/flexmeasures/pull/466>`_ and `PR #475 <https://www.github.com/FlexMeasures/flexmeasures/pull/475>`_]
* Avoid formatting datetime.timedelta durations as nominal ISO durations [see `PR #459 <https://www.github.com/FlexMeasures/flexmeasures/pull/459>`_]
* Account admins cannot add assets to other accounts any more; and they are shown a button for asset creation in UI [see `PR #488 <https://www.github.com/FlexMeasures/flexmeasures/pull/488>`_]

Infrastructure / Support
----------------------
* Docker compose stack now with Redis worker queue [see `PR #455 <https://www.github.com/FlexMeasures/flexmeasures/pull/455>`_]
* Allow access tokens to be passed as env vars as well [see `PR #443 <https://www.github.com/FlexMeasures/flexmeasures/pull/443>`_]
* Queue workers can get initialised without a custom name and name collisions are handled [see `PR #455 <https://www.github.com/FlexMeasures/flexmeasures/pull/455>`_]
* New API endpoint to get public assets [see `PR #461 <https://www.github.com/FlexMeasures/flexmeasures/pull/461>`_]
* Allow editing an asset's JSON attributes through the UI [see `PR #474 <https://www.github.com/FlexMeasures/flexmeasures/pull/474>`_]
* Allow a custom message when monitoring latest run of tasks [see `PR #489 <https://www.github.com/FlexMeasures/flexmeasures/pull/489>`_]


v0.10.1 | August 12, 2022
===========================

Bugfixes
-----------
* Fix some UI styling regressions in e.g. color contrast and hover effects [see `PR #441 <https://www.github.com/FlexMeasures/flexmeasures/pull/441>`_]


v0.10.0 | May 8, 2022
===========================

New features
-----------
* New design for FlexMeasures' UI back office [see `PR #425 <https://www.github.com/FlexMeasures/flexmeasures/pull/425>`_]
* Improve legibility of chart axes [see `PR #413 <https://www.github.com/FlexMeasures/flexmeasures/pull/413>`_]
* API provides health readiness check at /api/v3_0/health/ready [see `PR #416 <https://www.github.com/FlexMeasures/flexmeasures/pull/416>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/010-docker-styling/>`__.

Bugfixes
-----------
* Fix small problems in support for the admin-reader role & role-based authorization [see `PR #422 <https://www.github.com/FlexMeasures/flexmeasures/pull/422>`_]

Infrastructure / Support
----------------------
* Dockerfile to run FlexMeasures in container; also docker-compose file [see `PR #416 <https://www.github.com/FlexMeasures/flexmeasures/pull/416>`_]
* Unit conversion prefers shorter units in general [see `PR #415 <https://www.github.com/FlexMeasures/flexmeasures/pull/415>`_]
* Shorter CI builds in Github Actions by caching Python environment [see `PR #361 <https://www.github.com/FlexMeasures/flexmeasures/pull/361>`_]
* Allow to filter data by source using a tuple instead of a list [see `PR #421 <https://www.github.com/FlexMeasures/flexmeasures/pull/421>`_]


v0.9.4 | April 28, 2022
===========================

Bugfixes
--------
* Support checking validity of custom units (i.e. non-SI, non-currency units) [see `PR #424 <https://www.github.com/FlexMeasures/flexmeasures/pull/424>`_]


v0.9.3 | April 15, 2022
===========================

Bugfixes
--------
* Let registered plugins use CLI authorization [see `PR #411 <https://www.github.com/FlexMeasures/flexmeasures/pull/411>`_]


v0.9.2 | April 10, 2022
===========================

Bugfixes
--------
* Prefer unit conversions to short stock units [see `PR #412 <https://www.github.com/FlexMeasures/flexmeasures/pull/412>`_]
* Fix filter for selecting one deterministic belief per event, which was duplicating index levels [see `PR #414 <https://www.github.com/FlexMeasures/flexmeasures/pull/414>`_]


v0.9.1 | March 31, 2022
===========================

Bugfixes
--------
* Fix auth bug not masking locations of inaccessible assets on map [see `PR #409 <https://www.github.com/FlexMeasures/flexmeasures/pull/409>`_]
* Fix CLI auth check [see `PR #407 <https://www.github.com/FlexMeasures/flexmeasures/pull/407>`_]
* Fix resampling of sensor data for scheduling [see `PR #406 <https://www.github.com/FlexMeasures/flexmeasures/pull/406>`_]


v0.9.0 | March 25, 2022
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

New features
-----------
* Three new CLI commands for cleaning up your database: delete 1) unchanged beliefs, 2) NaN values or 3) a sensor and all of its time series data [see `PR #328 <https://www.github.com/FlexMeasures/flexmeasures/pull/328>`_]
* Add CLI option to pass a data unit when reading in time series data from CSV, so data can automatically be converted to the sensor unit [see `PR #341 <https://www.github.com/FlexMeasures/flexmeasures/pull/341>`_]
* Add CLI option to specify custom strings that should be interpreted as NaN values when reading in time series data from CSV [see `PR #357 <https://www.github.com/FlexMeasures/flexmeasures/pull/357>`_]
* Add CLI commands ``flexmeasures add sensor``, ``flexmeasures add asset-type``, ``flexmeasures add beliefs`` (which were experimental features before) [see `PR #337 <https://www.github.com/FlexMeasures/flexmeasures/pull/337>`_]
* Add CLI commands for showing organisational structure [see `PR #339 <https://www.github.com/FlexMeasures/flexmeasures/pull/339>`_]
* Add CLI command for showing time series data [see `PR #379 <https://www.github.com/FlexMeasures/flexmeasures/pull/379>`_]
* Add CLI command for attaching annotations to assets: ``flexmeasures add holidays`` adds public holidays [see `PR #343 <https://www.github.com/FlexMeasures/flexmeasures/pull/343>`_]
* Add CLI command for resampling existing sensor data to new resolution [see `PR #360 <https://www.github.com/FlexMeasures/flexmeasures/pull/360>`_]
* Add CLI command to delete an asset, with its sensors and data. [see `PR #395 <https://www.github.com/FlexMeasures/flexmeasures/pull/395>`_]
* Add CLI command to edit/add an attribute on an asset or sensor. [see `PR #380 <https://www.github.com/FlexMeasures/flexmeasures/pull/380>`_]
* Add CLI command to add a toy account for tutorials and trying things [see `PR #368 <https://www.github.com/FlexMeasures/flexmeasures/pull/368>`_]
* Add CLI command to create a charging schedule [see `PR #372 <https://www.github.com/FlexMeasures/flexmeasures/pull/372>`_]
* Support for percent (%) and permille (‰) sensor units [see `PR #359 <https://www.github.com/FlexMeasures/flexmeasures/pull/359>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/090-cli-developer-power/>`__.

Bugfixes
-----------

Infrastructure / Support
----------------------
* Plugins can import common FlexMeasures classes (like ``Asset`` and ``Sensor``) from a central place, using ``from flexmeasures import Asset, Sensor`` [see `PR #354 <https://www.github.com/FlexMeasures/flexmeasures/pull/354>`_]
* Adapt CLI command for entering some initial structure (``flexmeasures add structure``) to new datamodel [see `PR #349 <https://www.github.com/FlexMeasures/flexmeasures/pull/349>`_]
* Align documentation requirements with pip-tools [see `PR #384 <https://www.github.com/FlexMeasures/flexmeasures/pull/384>`_]
* Beginning API v3.0 - more REST-like, supporting assets, users and sensor data [see `PR #390 <https://www.github.com/FlexMeasures/flexmeasures/pull/390>`_ and `PR #392 <https://www.github.com/FlexMeasures/flexmeasures/pull/392>`_]


v0.8.0 | January 24, 2022
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).
.. warning:: In case you use FlexMeasures for simulations using ``FLEXMEASURES_MODE = "play"``, allowing to overwrite data is now set separately using  :ref:`overwrite-config`. Add ``FLEXMEASURES_ALLOW_DATA_OVERWRITE = True`` to your config settings to keep the old behaviour.
.. note:: v0.8.0 is doing much of the work we need to do to move to the new data model (see :ref:`note_on_datamodel_transition`). We hope to keep the migration steps for users very limited. One thing you'll notice is that we are copying over existing data to the new model (which will be kept in sync) with the `db upgrade` command (see warning above), which can take a few minutes.

New features
-----------
* Bar charts of sensor data for individual sensors, that can be navigated using a calendar [see `PR #99 <https://www.github.com/FlexMeasures/flexmeasures/pull/99>`_ and `PR #290 <https://www.github.com/FlexMeasures/flexmeasures/pull/290>`_]
* Charts with sensor data can be requested in one of the supported  [`vega-lite themes <https://github.com/vega/vega-themes#included-themes>`_] (incl. a dark theme) [see `PR #221 <https://www.github.com/FlexMeasures/flexmeasures/pull/221>`_]
* Mobile friendly (responsive) charts of sensor data, and such charts can be requested with a custom width and height [see `PR #313 <https://www.github.com/FlexMeasures/flexmeasures/pull/313>`_]
* Schedulers take into account round-trip efficiency if set [see `PR #291 <https://www.github.com/FlexMeasures/flexmeasures/pull/291>`_]
* Schedulers take into account min/max state of charge if set [see `PR #325 <https://www.github.com/FlexMeasures/flexmeasures/pull/325>`_]
* Fallback policies for charging schedules of batteries and Charge Points, in cases where the solver is presented with an infeasible problem [see `PR #267 <https://www.github.com/FlexMeasures/flexmeasures/pull/267>`_ and `PR #270 <https://www.github.com/FlexMeasures/flexmeasures/pull/270>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/080-better-scheduling-safer-data/>`__.

Deprecations
------------
* The Portfolio and Analytics views are deprecated [see `PR #321 <https://www.github.com/FlexMeasures/flexmeasures/pull/321>`_]

Bugfixes
-----------
* Fix recording time of schedules triggered by UDI events [see `PR #300 <https://www.github.com/FlexMeasures/flexmeasures/pull/300>`_]
* Set bar width of bar charts based on sensor resolution [see `PR #310 <https://www.github.com/FlexMeasures/flexmeasures/pull/310>`_]
* Fix bug in sensor data charts where data from multiple sources would be stacked, which incorrectly suggested that the data should be summed, whereas the data represents alternative beliefs [see `PR #228 <https://www.github.com/FlexMeasures/flexmeasures/pull/228>`_]

Infrastructure / Support
----------------------
* Account-based authorization, incl. new decorators for endpoints [see `PR #210 <https://www.github.com/FlexMeasures/flexmeasures/pull/210>`_]
* Central authorization policy which lets database models codify who can do what (permission-based) and relieve API endpoints from this [see `PR #234 <https://www.github.com/FlexMeasures/flexmeasures/pull/234>`_]
* Improve data specification for forecasting models using timely-beliefs data [see `PR #154 <https://www.github.com/FlexMeasures/flexmeasures/pull/154>`_]
* Properly attribute Mapbox and OpenStreetMap [see `PR #292 <https://www.github.com/FlexMeasures/flexmeasures/pull/292>`_]
* Allow plugins to register their custom config settings, so that FlexMeasures can check whether they are set up correctly [see `PR #230 <https://www.github.com/FlexMeasures/flexmeasures/pull/230>`_ and `PR #237 <https://www.github.com/FlexMeasures/flexmeasures/pull/237>`_]
* Add sensor method to obtain just its latest state (excl. forecasts) [see `PR #235 <https://www.github.com/FlexMeasures/flexmeasures/pull/235>`_]
* Migrate attributes of assets, markets and weather sensors to our new sensor model [see `PR #254 <https://www.github.com/FlexMeasures/flexmeasures/pull/254>`_ and `project 9 <https://www.github.com/FlexMeasures/flexmeasures/projects/9>`_]
* Migrate all time series data to our new sensor data model based on the `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib [see `PR #286 <https://www.github.com/FlexMeasures/flexmeasures/pull/286>`_ and `project 9 <https://www.github.com/FlexMeasures/flexmeasures/projects/9>`_]
* Support the new asset model (which describes the organisational structure, rather than sensors and data) in UI and API. Until the transition to our new data model is completed, the new API for assets is at `/api/dev/generic_assets`. [see `PR #251 <https://www.github.com/FlexMeasures/flexmeasures/pull/251>`_ and `PR #290 <https://www.github.com/FlexMeasures/flexmeasures/pulls/290>`_]
* Internal search methods return most recent beliefs by default, also for charts, which can make them load a lot faster [see `PR #307 <https://www.github.com/FlexMeasures/flexmeasures/pull/307>`_ and `PR #312 <https://www.github.com/FlexMeasures/flexmeasures/pull/312>`_]
* Support unit conversion for posting sensor data [see `PR #283 <https://www.github.com/FlexMeasures/flexmeasures/pull/283>`_ and `PR #293 <https://www.github.com/FlexMeasures/flexmeasures/pull/293>`_]
* Improve the core device scheduler to support dealing with asymmetric efficiency losses of individual devices, and with asymmetric up and down prices for deviating from previous commitments (such as a different feed-in tariff) [see `PR #291 <https://www.github.com/FlexMeasures/flexmeasures/pull/291>`_]
* Stop automatically triggering forecasting jobs when API calls save nothing new to the database, thereby saving redundant computation [see `PR #303 <https://www.github.com/FlexMeasures/flexmeasures/pull/303>`_]


v0.7.1 | November 8, 2021
===========================

Bugfixes
-----------
* Fix device messages, which were mixing up older and more recent schedules [see `PR #231 <https://www.github.com/FlexMeasures/flexmeasures/pull/231>`_]


v0.7.0 | October 26, 2021
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).
.. warning:: The config setting ``FLEXMEASURES_PLUGIN_PATHS`` has been renamed to ``FLEXMEASURES_PLUGINS``. The old name still works but is deprecated.

New features
-----------
* Set a logo for the top left corner with the new FLEXMEASURES_MENU_LOGO_PATH setting [see `PR #184 <https://www.github.com/FlexMeasures/flexmeasures/pull/184>`_]
* Add an extra style-sheet which applies to all pages with the new FLEXMEASURES_EXTRA_CSS_PATH setting [see `PR #185 <https://www.github.com/FlexMeasures/flexmeasures/pull/185>`_]
* Data sources can be further distinguished by what model (and version) they ran [see `PR #215 <https://www.github.com/FlexMeasures/flexmeasures/pull/215>`_]
* Enable plugins to automate tests with app context [see `PR #220 <https://www.github.com/FlexMeasures/flexmeasures/pull/220>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/070-professional-plugins/>`__.

Bugfixes
-----------
* Fix users resetting their own password [see `PR #195 <https://www.github.com/FlexMeasures/flexmeasures/pull/195>`_]
* Fix scheduling for heterogeneous settings, for instance, involving sensors with different time zones and/or resolutions [see `PR #207 <https://www.github.com/FlexMeasures/flexmeasures/pull/207>`_]
* Fix ``sensors/<id>/chart`` view [see `PR #223 <https://www.github.com/FlexMeasures/flexmeasures/pull/223>`_]

Infrastructure / Support
----------------------
* FlexMeasures plugins can be Python packages now. We provide `a cookie-cutter template <https://github.com/FlexMeasures/flexmeasures-plugin-template>`_ for this approach. [see `PR #182 <https://www.github.com/FlexMeasures/flexmeasures/pull/182>`_]
* Set default timezone for new users using the FLEXMEASURES_TIMEZONE config setting [see `PR #190 <https://www.github.com/FlexMeasures/flexmeasures/pull/190>`_]
* To avoid databases from filling up with irrelevant information, only beliefs data representing *changed beliefs are saved*, and *unchanged beliefs are dropped* [see `PR #194 <https://www.github.com/FlexMeasures/flexmeasures/pull/194>`_]
* Monitored CLI tasks can get better names for identification [see `PR #193 <https://www.github.com/FlexMeasures/flexmeasures/pull/193>`_]
* Less custom logfile location, document logging for devs [see `PR #196 <https://www.github.com/FlexMeasures/flexmeasures/pull/196>`_]
* Keep forecasting and scheduling jobs in the queues for only up to one day [see `PR #198 <https://www.github.com/FlexMeasures/flexmeasures/pull/198>`_]


v0.6.1 | October 23, 2021
===========================

New features
-----------

Bugfixes
-----------
* Fix (dev) CLI command for adding a GenericAssetType [see `PR #173 <https://www.github.com/FlexMeasures/flexmeasures/pull/173>`_]
* Fix (dev) CLI command for adding a Sensor [see `PR #176 <https://www.github.com/FlexMeasures/flexmeasures/pull/176>`_]
* Fix missing conversion of data source names and ids to DataSource objects [see `PR #178 <https://www.github.com/FlexMeasures/flexmeasures/pull/178>`_]
* Fix GetDeviceMessage to ensure chronological ordering of values [see `PR #216 <https://www.github.com/FlexMeasures/flexmeasures/pull/216>`_]

Infrastructure / Support
----------------------


v0.6.0 | September 3, 2021
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).
             In case you are using experimental developer features and have previously set up sensors, be sure to check out the upgrade instructions in `PR #157 <https://github.com/FlexMeasures/flexmeasures/pull/157>`_. Furthermore, if you want to create custom user/account relationships while upgrading (otherwise the upgrade script creates accounts based on email domains), check out the upgrade instructions in `PR #159 <https://github.com/FlexMeasures/flexmeasures/pull/159>`_. If you want to use both of these custom upgrade features, do the upgrade in two steps. First, as described in PR 157 and upgrading up to revision b6d49ed7cceb, then as described in PR 159 for the rest.

.. warning:: The config setting ``FLEXMEASURES_LISTED_VIEWS`` has been renamed to ``FLEXMEASURES_MENU_LISTED_VIEWS``.

.. warning:: Plugins now need to set their version on their module rather than on their blueprint. See the `documentation for writing plugins <https://flexmeasures.readthedocs.io/en/v0.6.0/dev/plugins.html>`_.

New features
-----------
* Multi-tenancy: Supporting multiple customers per FlexMeasures server, by introducing the `Account` concept. Accounts have users and assets associated. [see `PR #159 <https://www.github.com/FlexMeasures/flexmeasures/pull/159>`_ and `PR #163 <https://www.github.com/FlexMeasures/flexmeasures/pull/163>`_]
* In the UI, the root view ("/"), the platform name and the visible menu items can now be more tightly controlled (per account roles of the current user) [see also `PR #163 <https://www.github.com/FlexMeasures/flexmeasures/pull/163>`_]
* Analytics view offers grouping of all assets by location [see `PR #148 <https://www.github.com/FlexMeasures/flexmeasures/pull/148>`_]
* Add (experimental) endpoint to post sensor data for any sensor. Also supports our ongoing integration with data internally represented using the `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib [see `PR #147 <https://www.github.com/FlexMeasures/flexmeasures/pull/147>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v060-multi-tenancy-error-monitoring/>`__.

Bugfixes
-----------

Infrastructure / Support
----------------------
* Add possibility to send errors to Sentry [see `PR #143 <https://www.github.com/FlexMeasures/flexmeasures/pull/143>`_]
* Add CLI task to monitor if tasks ran successfully and recently enough [see `PR #146 <https://www.github.com/FlexMeasures/flexmeasures/pull/146>`_]
* Document how to use a custom favicon in plugins [see `PR #152 <https://www.github.com/FlexMeasures/flexmeasures/pull/152>`_]
* Allow plugins to register multiple Flask blueprints [see `PR #171 <https://www.github.com/FlexMeasures/flexmeasures/pull/171>`_]
* Continue experimental integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib: link multiple sensors to a single asset [see `PR #157 <https://github.com/FlexMeasures/flexmeasures/pull/157>`_]
* The experimental parts of the data model can now be visualised, as well, via `make show-data-model` (add the --dev option in Makefile) [also in `PR #157 <https://github.com/FlexMeasures/flexmeasures/pull/157>`_]


v0.5.0 | June 7, 2021
===========================

.. warning:: If you retrieve weather forecasts through FlexMeasures: we had to switch to OpenWeatherMap, as Dark Sky is closing. This requires an update to config variables ― the new setting is called ``OPENWEATHERMAP_API_KEY``.

New features
-----------
* Allow plugins to overwrite UI routes and customise the teaser on the login form [see `PR #106 <https://www.github.com/FlexMeasures/flexmeasures/pull/106>`_]
* Allow plugins to customise the copyright notice and credits in the UI footer [see `PR #123 <https://www.github.com/FlexMeasures/flexmeasures/pull/123>`_]
* Display loaded plugins in footer and support plugin versioning [see `PR #139 <https://www.github.com/FlexMeasures/flexmeasures/pull/139>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v050-openweathermap-plugin-customisation/>`__.

Bugfixes
-----------
* Fix last login date display in user list [see `PR #133 <https://www.github.com/FlexMeasures/flexmeasures/pull/133>`_]
* Choose better forecasting horizons when weather data is posted [see `PR #131 <https://www.github.com/FlexMeasures/flexmeasures/pull/131>`_]

Infrastructure / Support
----------------------
* Add tutorials on how to add and read data from FlexMeasures via its API [see `PR #130 <https://www.github.com/FlexMeasures/flexmeasures/pull/130>`_]
* For weather forecasts, switch from Dark Sky (closed from Aug 1, 2021) to OpenWeatherMap API [see `PR #113 <https://www.github.com/FlexMeasures/flexmeasures/pull/113>`_]
* Entity address improvements: add new id-based `fm1` scheme, better documentation and more validation support of entity addresses [see `PR #81 <https://www.github.com/FlexMeasures/flexmeasures/pull/81>`_]
* Re-use the database between automated tests, if possible. This shaves 2/3rd off of the time it takes for the FlexMeasures test suite to run [see `PR #115 <https://www.github.com/FlexMeasures/flexmeasures/pull/115>`_]
* Make assets use MW as their default unit and enforce that in CLI, as well (API already did) [see `PR #108 <https://www.github.com/FlexMeasures/flexmeasures/pull/108>`_]
* Let CLI package and plugins use Marshmallow Field definitions [see `PR #125 <https://www.github.com/FlexMeasures/flexmeasures/pull/125>`_]
* add time_utils.get_recent_clock_time_window() function [see `PR #135 <https://www.github.com/FlexMeasures/flexmeasures/pull/135>`_]


v0.4.1 | May 7, 2021
===========================

Bugfixes
-----------
* Fix regression when editing assets in the UI [see `PR #122 <https://www.github.com/FlexMeasures/flexmeasures/pull/122>`_]
* Fixed a regression that stopped asset, market and sensor selection from working [see `PR #117 <https://www.github.com/FlexMeasures/flexmeasures/pull/117>`_]
* Prevent logging out user when clearing the session [see `PR #112 <https://www.github.com/FlexMeasures/flexmeasures/pull/112>`_]
* Prevent user type data source to be created without setting a user [see `PR #111 <https://github.com/FlexMeasures/flexmeasures/pull/111>`_]


v0.4.0 | April 29, 2021
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

New features
-----------
* Allow for views and CLI functions to come from plugins [see also `PR #91 <https://github.com/FlexMeasures/flexmeasures/pull/91>`_]
* Configure the UI menu with ``FLEXMEASURES_LISTED_VIEWS`` [see `PR #91 <https://github.com/FlexMeasures/flexmeasures/pull/91>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v040-plugin-support/>`__.

Bugfixes
-----------
* Asset edit form displayed wrong error message. Also enabled the asset edit form to display the invalid user input back to the user [see `PR #93 <https://www.github.com/FlexMeasures/flexmeasures/pull/93>`_]

Infrastructure / Support
----------------------
* Updated dependencies, including Flask-Security-Too [see `PR #82 <https://www.github.com/FlexMeasures/flexmeasures/pull/82>`_]
* Improved documentation after user feedback [see `PR #97 <https://www.github.com/FlexMeasures/flexmeasures/pull/97>`_]
* Begin experimental integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib: Sensor data as TimedBeliefs [see `PR #79 <https://www.github.com/FlexMeasures/flexmeasures/pull/79>`_ and `PR #99 <https://github.com/FlexMeasures/flexmeasures/pull/99>`_]
* Add sensors with CLI command currently meant for developers only [see `PR #83 <https://github.com/FlexMeasures/flexmeasures/pull/83>`_]
* Add data (beliefs about sensor events) with CLI command currently meant for developers only [see `PR #85 <https://github.com/FlexMeasures/flexmeasures/pull/85>`_ and `PR #103 <https://github.com/FlexMeasures/flexmeasures/pull/103>`_]


v0.3.1 | April 9, 2021
===========================

Bugfixes
--------
* PostMeterData endpoint was broken in API v2.0 [see `PR #95 <https://www.github.com/FlexMeasures/flexmeasures/pull/95>`_]


v0.3.0 | April 2, 2021
===========================

New features
-----------
* FlexMeasures can be installed with ``pip`` and its CLI commands can be run with ``flexmeasures`` [see `PR #54 <https://www.github.com/FlexMeasures/flexmeasures/pull/54>`_]
* Optionally setting recording time when posting data [see `PR #41 <https://www.github.com/FlexMeasures/flexmeasures/pull/41>`_]
* Add assets and weather sensors with CLI commands [see `PR #74 <https://github.com/FlexMeasures/flexmeasures/pull/74>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v030-pip-install-cli-commands-belief-time-api/>`__.

Bugfixes
--------
* Show screenshots in documentation and add some missing content [see `PR #60 <https://www.github.com/FlexMeasures/flexmeasures/pull/60>`_]
* Documentation listed 2.0 API endpoints twice [see `PR #59 <https://www.github.com/FlexMeasures/flexmeasures/pull/59>`_]
* Better xrange and title if only schedules are plotted [see `PR #67 <https://www.github.com/FlexMeasures/flexmeasures/pull/67>`_]
* User page did not list number of assets correctly [see `PR #64 <https://www.github.com/FlexMeasures/flexmeasures/pull/64>`_]
* Missing *postPrognosis* endpoint for >1.0 API blueprints [part of `PR #41 <https://www.github.com/FlexMeasures/flexmeasures/pull/41>`_]

Infrastructure / Support
----------------------
* Added concept pages to documentation [see `PR #65 <https://www.github.com/FlexMeasures/flexmeasures/pull/65>`_]
* Dump and restore postgres database as CLI commands [see `PR #68 <https://github.com/FlexMeasures/flexmeasures/pull/68>`_]
* Improved installation tutorial as part of [`PR #54 <https://www.github.com/FlexMeasures/flexmeasures/pull/54>`_]
* Moved developer docs from Readmes into the main documentation  [see `PR #73 <https://github.com/FlexMeasures/flexmeasures/pull/73>`_]
* Ensured unique sensor ids for all sensors [see `PR #70 <https://github.com/FlexMeasures/flexmeasures/pull/70>`_ and (fix) `PR #77 <https://github.com/FlexMeasures/flexmeasures/pull/77>`_]


v0.2.3 | February 27, 2021
===========================

New features
------------
* Power charts available via the API [see `PR #39 <https://www.github.com/FlexMeasures/flexmeasures/pull/39>`_]
* User management via the API [see `PR #25 <https://www.github.com/FlexMeasures/flexmeasures/pull/25>`_]
* Better visibility of asset icons on maps [see `PR #30 <https://www.github.com/FlexMeasures/flexmeasures/pull/30>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v023-user-api-power-chart-api-better-icons/>`__.

Bugfixes
--------
* Fix maps on new asset page (update MapBox lib) [see `PR #27 <https://www.github.com/FlexMeasures/flexmeasures/pull/27>`_]
* Some asset links were broken [see `PR #20 <https://www.github.com/FlexMeasures/flexmeasures/pull/20>`_]
* Password reset link on account page was broken [see `PR #23 <https://www.github.com/FlexMeasures/flexmeasures/pull/23>`_]

Infrastructure / Support
----------------------
* CI via Github Actions [see `PR #1 <https://www.github.com/FlexMeasures/flexmeasures/pull/1>`_]
* Integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`__ lib: Sensors [see `PR #13 <https://www.github.com/FlexMeasures/flexmeasures/pull/13>`_]
* Apache 2.0 license [see `PR #16 <https://www.github.com/FlexMeasures/flexmeasures/pull/16>`_]
* Load js & css from CDN [see `PR #21 <https://www.github.com/FlexMeasures/flexmeasures/pull/21>`_]
* Start using marshmallow for input validation, also introducing ``HTTP status 422 (Unprocessable Entity)`` in the API [see `PR #25 <https://www.github.com/FlexMeasures/flexmeasures/pull/25>`_]
* Replace ``solarpy`` with ``pvlib`` (due to license conflict) [see `PR #16 <https://www.github.com/FlexMeasures/flexmeasures/pull/16>`_]
* Stop supporting the creation of new users on asset creation (to reduce complexity) [see `PR #36 <https://www.github.com/FlexMeasures/flexmeasures/pull/36>`_]

