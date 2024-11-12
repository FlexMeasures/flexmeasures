
**********************
FlexMeasures Changelog
**********************


v0.23.1 | November 12, 2024
============================

Bugfixes
-----------
* Correct unit conversion of reporter output to output sensor [see `PR #1238 <https://github.com/FlexMeasures/flexmeasures/pull/1238>`_]


v0.23.0 | September 18, 2024
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/023-data-insights-and-white-labelling/>`_.

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

New features
-------------
* New chart type on sensor page: histogram [see `PR #1143 <https://github.com/FlexMeasures/flexmeasures/pull/1143>`_]
* Add basic sensor info to sensor page [see `PR #1115 <https://github.com/FlexMeasures/flexmeasures/pull/1115>`_]
* Add `Statistics` table on the sensor page and also add `api/v3_0/sensors/<id>/stats` endpoint to get sensor statistics [see `PR #1116 <https://github.com/FlexMeasures/flexmeasures/pull/1116>`_]
* Support adding custom titles to the graphs on the asset page, by extending the ``sensors_to_show`` format [see `PR #1125 <https://github.com/FlexMeasures/flexmeasures/pull/1125>`_ and `PR #1177 <https://github.com/FlexMeasures/flexmeasures/pull/1177>`_]
* Support zoom-in action on the asset and sensor charts [see `PR #1130 <https://github.com/FlexMeasures/flexmeasures/pull/1130>`_]
* Speed up loading the assets page, by making the pagination backend-based and adding support for that in the API, and by enabling to query all accounts one can see in a single call (for admins and consultants) [see `PR #988 <https://github.com/FlexMeasures/flexmeasures/pull/988>`_]
* Added Primary and Secondary colors to account for white-labelled UI themes [see `PR #1137 <https://github.com/FlexMeasures/flexmeasures/pull/1137>`_]
* Added Logo URL to account for white-labelled UI themes [see `PR #1145 <https://github.com/FlexMeasures/flexmeasures/pull/1145>`_]
* Added PopUp form to edit account details [see `PR #1152 <https://github.com/FlexMeasures/flexmeasures/pull/1152>`_]
* When listing past jobs on the `Tasks` page, show the most recent jobs first [see `PR #1163 <https://github.com/FlexMeasures/flexmeasures/pull/1163>`_]
* Introduce the ``VariableQuantityField`` to allow three ways of passing a variable quantity in most of the ``flex-model`` and ``flex-context`` fields [see `PR #1127 <https://github.com/FlexMeasures/flexmeasures/pull/1127>`_ and `PR #1138 <https://github.com/FlexMeasures/flexmeasures/pull/1138>`_]
* Support directly passing a fixed price in the ``flex-context`` using the new fields ``consumption-price`` and ``production-price``, which are meant to replace the ``consumption-price-sensor`` and ``production-price-sensor`` fields, respectively [see `PR #1028 <https://github.com/FlexMeasures/flexmeasures/pull/1028>`_]

Infrastructure / Support
----------------------
* Save beliefs faster by bulk saving [see `PR #1159 <https://github.com/FlexMeasures/flexmeasures/pull/1159>`_]
* Support new single-belief fast track (looking up only one belief) [see `PR #1067 <https://github.com/FlexMeasures/flexmeasures/pull/1067>`_]
* Add new annotation types: ``"error"`` and ``"warning"`` [see `PR #1131 <https://github.com/FlexMeasures/flexmeasures/pull/1131>`_ and `PR #1150 <https://github.com/FlexMeasures/flexmeasures/pull/1150>`_]
* When deleting a sensor, asset or account, delete any annotations that belong to them [see `PR #1151 <https://github.com/FlexMeasures/flexmeasures/pull/1151>`_]
* Removed deprecated ``app.schedulers`` and ``app.forecasters`` (use ``app.data_generators["scheduler"]`` and ``app.data_generators["forecaster"]`` instead) [see `PR #1098 <https://github.com/FlexMeasures/flexmeasures/pull/1098/>`_]
* Save beliefs faster by bulk saving [see `PR #1159 <https://github.com/FlexMeasures/flexmeasures/pull/1159>`_]
* Introduced dynamic, JavaScript-generated toast notifications. [see `PR #1152 <https://github.com/FlexMeasures/flexmeasures/pull/1152>`_]

Bugfixes
-----------
* Fix string length exceeding the 255-character limit in the `event` field of `AssetAuditLog` by truncating long updates and logging each field or attribute change individually. [see `PR #1162 <https://github.com/FlexMeasures/flexmeasures/pull/1162>`_]
* Fix image carousel on the login page [see `PR #1154 <https://github.com/FlexMeasures/flexmeasures/pull/1154>`_]
* Fix styling for User and Documentation menu items [see `PR #1140 <https://github.com/FlexMeasures/flexmeasures/pull/1140>`_]
* Fix styling of sensor page, especially the graph chart dropdown [see `PR #1148 <https://github.com/FlexMeasures/flexmeasures/pull/1148>`_]
* Fix posting a single instantaneous belief [see `PR #1129 <https://github.com/FlexMeasures/flexmeasures/pull/1129>`_]
* Allow reassigning a public asset to private ownership using the ``flexmeasures edit transfer-ownership`` CLI command [see `PR #1123 <https://github.com/FlexMeasures/flexmeasures/pull/1123>`_]
* Fix missing value on spring :abbr:`DST (Daylight Saving Time)` transition for ``PandasReporter`` using daily sensor as input [see `PR #1122 <https://github.com/FlexMeasures/flexmeasures/pull/1122>`_]
* Fix date range persistence on session across different pages [see `PR #1165 <https://github.com/FlexMeasures/flexmeasures/pull/1165>`_]
* Fix issue with account creation failing when the --logo-url flag is omitted. [see related PRs `PR #1167 <https://github.com/FlexMeasures/flexmeasures/pull/1167>`_ and `PR #1145 <https://github.com/FlexMeasures/flexmeasures/pull/1145>`_]
* Fix ordering of audit logs and job list on status page [see PR `PR #1179 <https://github.com/FlexMeasures/flexmeasures/pull/1179>_`]


v0.22.0 | June 29, 2024
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/022-editing-flex-context/>`_.

New features
-------------
* Add `asset/<id>/auditlog` to view asset related actions [see `PR #1067 <https://github.com/FlexMeasures/flexmeasures/pull/1067>`_]
* On the `/sensor/id` page, allow to link to it with a date range and to copy current view as URL [see `PR #1094 <https://github.com/FlexMeasures/flexmeasures/pull/1094>`_]
* Flex-context (price sensors and inflexible device sensors) can now be set on the asset page (and are part of GenericAsset model) [see `PR #1059 <https://github.com/FlexMeasures/flexmeasures/pull/1059/>`_]
* On the asset page's default view, facilitate comparison by showing the two default sensors together if they record the same unit [see `PR #1066 <https://github.com/FlexMeasures/flexmeasures/pull/1066>`_]
* Add flex-context sensors to status page [see `PR #1102 <https://github.com/FlexMeasures/flexmeasures/pull/1102>`_]
* Show tooltips on (mobile) touch screen [see `PR #1062 <https://github.com/FlexMeasures/flexmeasures/pull/1062>`_]

Infrastructure / Support
----------------------
* Add MailHog to docker-compose stack for testing email functionality [see `PR #1112 <https://github.com/FlexMeasures/flexmeasures/pull/1112>`_]
* Allow installing dependencies in docker-compose worker [see `PR #1057 <https://github.com/FlexMeasures/flexmeasures/pull/1057/>`_]
* Add unit conversion to the input and output data of the ``PandasReporter`` [see `PR #1044 <https://github.com/FlexMeasures/flexmeasures/pull/1044/>`_]
* Add option ``droplevels`` to the ``PandasReporter`` to drop all the levels except the ``event_start`` and ``event_value`` [see `PR #1043 <https://github.com/FlexMeasures/flexmeasures/pull/1043/>`_]
* ``PandasReporter`` accepts the parameter ``use_latest_version_only`` to filter input data [see `PR #1045 <https://github.com/FlexMeasures/flexmeasures/pull/1045/>`_]
* ``flexmeasures show beliefs`` uses the entity path (`<Account>/../<Sensor>`) in case of duplicated sensors [see `PR #1026 <https://github.com/FlexMeasures/flexmeasures/pull/1026/>`_]
* Add ``--resolution`` option to ``flexmeasures show chart`` to produce charts in different time resolutions [see `PR #1007 <https://github.com/FlexMeasures/flexmeasures/pull/1007/>`_]
* Add ``FLEXMEASURES_JSON_COMPACT`` config setting and deprecate ``JSONIFY_PRETTYPRINT_REGULAR`` setting [see `PR #1090 <https://github.com/FlexMeasures/flexmeasures/pull/1090/>`_]

Bugfixes
-----------
* Fix ordering of jobs on the asset status page [see `PR #1106 <https://github.com/FlexMeasures/flexmeasures/pull/1106>`_]
* Relax max staleness for status page using 2 * event_resolution as default instead of immediate staleness [see `PR #1108 <https://github.com/FlexMeasures/flexmeasures/pull/1108>`_]


v0.21.0 | May 16, 2024
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/021-service-better-status-and-audit/>`_.

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

New features
-------------
* Add `asset/<id>/status` page to view asset statuses [see `PR #941 <https://github.com/FlexMeasures/flexmeasures/pull/941>`_ and `PR #1035 <https://github.com/FlexMeasures/flexmeasures/pull/1035>`_]
* Add `account/<id>/auditlog` and `user/<id>/auditlog` to view user and account related actions [see `PR #1042 <https://github.com/FlexMeasures/flexmeasures/pull/1042>`_]
* Support ``start_date`` and ``end_date`` query parameters for the asset page [see `PR #1030 <https://github.com/FlexMeasures/flexmeasures/pull/1030>`_]
* In plots, add the asset name to the title of the tooltip to improve the identification of the lines [see `PR #1054 <https://github.com/FlexMeasures/flexmeasures/pull/1054>`_]
* On asset page, show sensor IDs in sensor table [see `PR #1053 <https://github.com/FlexMeasures/flexmeasures/pull/1053>`_]

Bugfixes
-----------
* Prevent the time window in the UI from moving to the latest data when refreshing the asset page [see `PR #1046 <https://github.com/FlexMeasures/flexmeasures/pull/1046>`_ and `PR #1056 <https://github.com/FlexMeasures/flexmeasures/pull/1056>`_]

Infrastructure / Support
----------------------
* Include started, deferred and scheduled jobs in the overview printed by the CLI command ``flexmeasures jobs show-queues`` [see `PR #1036 <https://github.com/FlexMeasures/flexmeasures/pull/1036>`_]
* Make it as convenient to clear deferred or scheduled jobs from a queue as it was to clear failed jobs from a queue [see `PR #1037 <https://github.com/FlexMeasures/flexmeasures/pull/1037>`_]


v0.20.1 | May 7, 2024
============================

Bugfixes
-----------
* Prevent **p**\ lay/**p**\ ause/**s**\ top of replays when editing a text field in the UI [see `PR #1024 <https://github.com/FlexMeasures/flexmeasures/pull/1024>`_]
* Skip unit conversion of :abbr:`SoC (state of charge)` related fields that are defined as sensors in a ``flex-model`` (specifically, ``soc-maxima``, ``soc-minima`` and ``soc-targets`` [see `PR #1047 <https://github.com/FlexMeasures/flexmeasures/pull/1047>`_]


v0.20.0 | March 26, 2024
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/020-faster-data-reads/>`__.

.. warning:: From this version on, the config setting ``FLEXMEASURES_FORCE_HTTPS`` decides whether to enforce HTTPS on requests - and it defaults to ``False``. Previously, this was governed by ``FLASK_ENV`` or ``FLEXMEASURES_ENV`` being set to something else than ``"documentation"`` or ``"development"``. This new way is more clear, but you might be in need of using this setting before upgrading.

New features
-------------
* Add command ``flexmeasures edit transfer-ownership`` to transfer the ownership of an asset and its children from one account to another [see `PR #983 <https://github.com/FlexMeasures/flexmeasures/pull/983>`_]
* Support defining the ``site-power-capacity``, ``site-consumption-capacity`` and ``site-production-capacity`` as a sensor in the API and CLI [see `PR #985 <https://github.com/FlexMeasures/flexmeasures/pull/985>`_]
* Support defining the ``soc-minima``, ``soc-maxima`` and ``soc-targets`` as sensors in the API [see `PR #996 <https://github.com/FlexMeasures/flexmeasures/pull/996>`_]
* Support defining inflexible power sensors with arbitrary power and energy units [see `PR #1007 <https://github.com/FlexMeasures/flexmeasures/pull/1007>`_]
* Support saving beliefs with a ``belief_horizon`` in the ``PandasReporter`` [see `PR #1013 <https://github.com/FlexMeasures/flexmeasures/pull/1013>`_]
* Skip the check of the output event resolution in any ``Reporter`` with the field ``check_output_resolution`` [see `PR #1009 <https://github.com/FlexMeasures/flexmeasures/pull/1009>`_]

Bugfixes
-----------
* Use minimum event resolution of the input (instead of the output) sensors for the belief search parameters [see `PR #1010 <https://github.com/FlexMeasures/flexmeasures/pull/1010>`_]

Infrastructure / Support
----------------------
* Align map layers with custom asset types in the UI's dashboard, also facilitating capturing asset types defined within FlexMeasures plugins [see `PR #1017 <https://github.com/FlexMeasures/flexmeasures/pull/1017>`_]
* Improve processing time for deleting beliefs via CLI [see `PR #1005 <https://github.com/FlexMeasures/flexmeasures/pull/1005>`_]
* Support deleting beliefs via CLI for all offspring assets at once [see `PR #1003 <https://github.com/FlexMeasures/flexmeasures/pull/1003>`_]
* Add setting ``FLEXMEASURES_FORCE_HTTPS`` to explicitly toggle if HTTPS should be used for all requests [see `PR #1008 <https://github.com/FlexMeasures/flexmeasures/pull/1008>`_]
* Make flexmeasures installable locally on macOS [see `PR #1000 <https://github.com/FlexMeasures/flexmeasures/pull/1000>`_]
* Align API endpoint policy w.r.t. trailing slash [see `PR #1014 <https://github.com/FlexMeasures/flexmeasures/pull/1014>`_]


v0.19.2 | March 1, 2024
============================

.. note:: Optionally, run ``flexmeasures db upgrade`` after upgrading to this version for enhanced database performance on time series queries.

* Upgrade timely-beliefs to enhance our main time series query and fix a database index on time series data, leading to significantly better performance [see `PR #992 <https://github.com/FlexMeasures/flexmeasures/pull/992>`_]
* Fix server error on loading the asset page for a public asset, due to a bug in the breadcrumb's sibling navigation [see `PR #991 <https://github.com/FlexMeasures/flexmeasures/pull/991>`_]
* Restore compatibility with the `flexmeasures-openweathermap plugin <https://github.com/SeitaBV/flexmeasures-openweathermap>`_ by fixing the query for the closest weather sensor to a given asset [see `PR #997 <https://github.com/FlexMeasures/flexmeasures/pull/997>`_]


v0.19.1 | February 26, 2024
============================

* Support defining the ``power-capacity`` as a sensor in the API and CLI [see `PR #987 <https://github.com/FlexMeasures/flexmeasures/pull/987>`_]


v0.19.0 | February 18, 2024
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/019-asset-nesting/>`__.

.. warning:: This version replaces ``FLASK_ENV`` with ``FLEXMEASURES_ENV`` (``FLASK_ENV`` will still be used as a fallback).

New features
-------------
* List child assets on the asset page [see `PR #967 <https://github.com/FlexMeasures/flexmeasures/pull/967>`_]
* Expand the UI's breadcrumb functionality with the ability to navigate directly to sibling assets and sensors using their child-parent relationship [see `PR #977 <https://github.com/FlexMeasures/flexmeasures/pull/977>`_]
* Enable the use of QuantityOrSensor fields for the ``flexmeasures add schedule for-storage`` CLI command [see `PR #966 <https://github.com/FlexMeasures/flexmeasures/pull/966>`_]
* CLI support for showing/savings time series data for a given type of source only, with the new ``--source-type`` option of ``flexmeasures show beliefs``, which let's you filter out schedules, forecasts, or data POSTed by users (through the API), which each have a different source type [see `PR #976 <https://github.com/FlexMeasures/flexmeasures/pull/976>`_]
* New CLI command ``flexmeasures delete beliefs`` to delete all beliefs on a given sensor (or multiple sensors) or on sensors of a given asset (or multiple assets) [see `PR #975 <https://github.com/FlexMeasures/flexmeasures/pull/975>`_]
* Support for defining the storage efficiency as a sensor or quantity for the ``StorageScheduler`` [see `PR #965 <https://github.com/FlexMeasures/flexmeasures/pull/965>`_]
* Support a less verbose way of setting the same :abbr:`SoC (state of charge)` constraint for a given time window [see `PR #899 <https://github.com/FlexMeasures/flexmeasures/pull/899>`_]

Infrastructure / Support
----------------------
* Deprecate use of flask's ``FLASK_ENV`` variable and replace it with ``FLEXMEASURES_ENV`` [see `PR #907 <https://github.com/FlexMeasures/flexmeasures/pull/907>`_]
* Streamline CLI option naming by favoring ``--<entity>`` over ``--<entity>-id`` [see `PR #946 <https://github.com/FlexMeasures/flexmeasures/pull/946>`_]
* Documentation: improve index page, installation overview, feature overview incl. flex-model overview and UI screenshots [see `PR #953 <https://github.com/FlexMeasures/flexmeasures/pull/953>`_]
* Faster database queries of time series data by upgrading SQLAlchemy and timely-beliefs [see `PR #938 <https://github.com/FlexMeasures/flexmeasures/pull/938>`_]



v0.18.2 | February 26, 2024
============================

* Convert unit of the power capacities to ``MW`` instead of that of the storage power sensor [see `PR #979 <https://github.com/FlexMeasures/flexmeasures/pull/979>`_]
* Automatically update table navigation in the UI without requiring users to hard refresh their browser [see `PR #961 <https://github.com/FlexMeasures/flexmeasures/pull/961>`_]
* Updated documentation to enhance clarity for integrating plugins within the FlexMeasures Docker container [see `PR #958 <https://github.com/FlexMeasures/flexmeasures/pull/958>`_]
* Support defining the ``power-capacity`` as a sensor in the API [see `PR #987 <https://github.com/FlexMeasures/flexmeasures/pull/987>`_]


v0.18.1 | January 15, 2024
============================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

Bugfixes
-----------
* Fix database migrations meant to clean up deprecated tables [see `PR #960 <https://github.com/FlexMeasures/flexmeasures/pull/960>`_]
* Allow showing beliefs (plot and file export) via the CLI for sensors with non-unique names [see `PR #947 <https://github.com/FlexMeasures/flexmeasures/pull/947>`_]
* Added Redis credentials to the Docker Compose configuration for the web server to ensure proper interaction with the Redis queue [see `PR #945 <https://github.com/FlexMeasures/flexmeasures/pull/945>`_]
* Fix API version listing (GET /api/v3_0) for hosts running on Python 3.8 [see `PR #917 <https://github.com/FlexMeasures/flexmeasures/pull/917>`_ and `PR #950 <https://github.com/FlexMeasures/flexmeasures/pull/950>`_]
* Fix the validation of the option ``--parent-asset`` of command ``flexmeasures add asset`` [see `PR #959 <https://github.com/FlexMeasures/flexmeasures/pull/959>`_]


v0.18.0 | December 23, 2023
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/018-better-use-of-future-knowledge/>`__.

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``). If this fails, update to ``flexmeasures==0.18.1`` first (and then run ``flexmeasures db upgrade``).

New features
-------------
* Better navigation experience through listings (sensors / assets / users / accounts) in the :abbr:`UI (user interface)`, by heading to the selected entity upon a click (or CTRL + click) anywhere within a row [see `PR #923 <https://github.com/FlexMeasures/flexmeasures/pull/923>`_]
* Introduce a breadcrumb to navigate through assets and sensor pages using its child-parent relationship [see `PR #930 <https://github.com/FlexMeasures/flexmeasures/pull/930>`_]
* Define device-level power constraints as sensors to create schedules with changing power limits [see `PR #897 <https://github.com/FlexMeasures/flexmeasures/pull/897>`_]
* Allow to provide external storage usage or gain components using the ``soc-usage`` and ``soc-gain`` fields of the ``flex-model`` [see `PR #906 <https://github.com/FlexMeasures/flexmeasures/pull/906>`_]
* Define time-varying charging and discharging efficiencies as sensors or as constant values which allows to define the :abbr:`COP (coefficient of performance)` [see `PR #933 <https://github.com/FlexMeasures/flexmeasures/pull/933>`_]

Infrastructure / Support
----------------------
* Align database and models of ``annotations``, ``data_sources``, and ``timed_belief`` [see `PR #929 <https://github.com/FlexMeasures/flexmeasures/pull/929>`_]
* New documentation section on constructing a flex model for :abbr:`V2G (vehicle-to-grid)` [see `PR #885 <https://github.com/FlexMeasures/flexmeasures/pull/885>`_]
* Allow charts in plugins to show currency codes (such as EUR) as currency symbols (€) [see `PR #922 <https://github.com/FlexMeasures/flexmeasures/pull/922>`_]
* Remove obsolete database tables ``price``, ``power``, ``market``, ``market_type``, ``weather``, ``asset``, and ``weather_sensor`` [see `PR #921 <https://github.com/FlexMeasures/flexmeasures/pull/921>`_]
* New flexmeasures configuration setting ``FLEXMEASURES_ENFORCE_SECURE_CONTENT_POLICY`` for upgrading insecure `http` requests to secured requests `https` [see `PR #920 <https://github.com/FlexMeasures/flexmeasures/pull/920>`_]

Bugfixes
-----------
* Give ``admin-reader`` role access to the RQ Scheduler dashboard [see `PR #901 <https://github.com/FlexMeasures/flexmeasures/pull/901>`_]
* Assets without a geographical position (i.e. no lat/lng coordinates) can be edited through the UI [see `PR #924 <https://github.com/FlexMeasures/flexmeasures/pull/924>`_]


v0.17.1 | December 7, 2023
============================

Bugfixes
-----------
* Show `Assets`, `Users`, `Tasks` and `Accounts` pages in the navigation bar for the ``admin-reader`` role [see `PR #900 <https://github.com/FlexMeasures/flexmeasures/pull/900>`_]
* Reduce worker logs when datetime exceeds the end of the schedule [see `PR #918 <https://github.com/FlexMeasures/flexmeasures/pull/918>`_]
* Fix infeasible problem due to incorrect estimation of the big-M value [see `PR #905 <https://github.com/FlexMeasures/flexmeasures/pull/905>`_]
* [Incomplete fix; full fix in v0.18.1] Fix API version listing (GET /api/v3_0) for hosts running on Python 3.8 [see `PR #917 <https://github.com/FlexMeasures/flexmeasures/pull/917>`_]


v0.17.0 | November 8, 2023
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/017-consultancy/>`__.

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

New features
-------------
- Different site-level production and consumption limits can be defined for the storage scheduler via the API (``flex-context``) or via asset attributes [see `PR #884 <https://github.com/FlexMeasures/flexmeasures/pull/884>`_]
- Scheduling data better distinguishes (e.g. in chart tooltips) when a schedule was the result of a fallback mechanism, by splitting off the fallback mechanism from the main scheduler (as a separate job) [see `PR #846 <https://github.com/FlexMeasures/flexmeasures/pull/846>`_]
- New accounts can set a consultancy relationship with another account to give read access to external consultants [see `PR #877 <https://github.com/FlexMeasures/flexmeasures/pull/877>`_ and `PR #892 <https://github.com/FlexMeasures/flexmeasures/pull/892>`_]

Infrastructure / Support
----------------------
- Introduce a new one-to-many relation between assets, allowing the definition of an asset's parent (which is also an asset), which leads to a hierarchical relationship that enables assets to be related in a structured manner [see `PR #855 <https://github.com/FlexMeasures/flexmeasures/pull/855>`_ and `PR #874 <https://github.com/FlexMeasures/flexmeasures/pull/874>`_]
- Introduce a new format for the output of ``Scheduler`` to prepare for multiple outputs [see `PR #879 <https://github.com/FlexMeasures/flexmeasures/pull/879>`_]


v0.16.1 | October 2, 2023
============================

Bugfixes
-----------
* Fix infeasible problem due to incorrect parsing of soc units of the ``soc-minima`` and ``soc-maxima`` fields within the ``flex-model`` field [see `PR #864 <https://github.com/FlexMeasures/flexmeasures/pull/864>`_]


v0.16.0 | September 27, 2023
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/016-profitloss-reporter/>`__.

New features
-------------
* Introduce new reporter to compute profit/loss due to electricity flows: ``ProfitOrLossReporter`` [see `PR #808 <https://github.com/FlexMeasures/flexmeasures/pull/808>`_ and `PR #844 <https://github.com/FlexMeasures/flexmeasures/pull/844>`_]
* Charts visible in the UI can be exported to PNG or SVG formats in a more automated fashion, using the new CLI command flexmeasures show chart [see `PR #833 <https://github.com/FlexMeasures/flexmeasures/pull/833>`_]
* Chart data visible in the UI can be exported to CSV format [see `PR #849 <https://github.com/FlexMeasures/flexmeasures/pull/849>`_]
* Sensor charts showing instantaneous observations can be interpolated by setting the ``interpolate`` sensor attribute to one of the `supported Vega-Lite interpolation methods <https://vega.github.io/vega-lite/docs/area.html#properties>`_ [see `PR #851 <https://github.com/FlexMeasures/flexmeasures/pull/851>`_]
* API users can ask for a schedule to take into account an explicit ``power-capacity`` (flex-model) and/or ``site-power-capacity`` (flex-context), thereby overriding any existing defaults for their asset [see `PR #850 <https://github.com/FlexMeasures/flexmeasures/pull/850>`_]
* API users (and hosts) are warned in case a fallback scheduling policy has been used to create their schedule (as part of the the `/sensors/<id>/schedules/<uuid>` (GET) response message) [see `PR #859 <https://github.com/FlexMeasures/flexmeasures/pull/859>`_]

Infrastructure / Support
----------------------
* Allow additional datetime conversions to quantitative time units, specifically, from timezone-naive and/or dayfirst datetimes, which can be useful when importing data [see `PR #831 <https://github.com/FlexMeasures/flexmeasures/pull/831>`_]
* Add a new tutorial to explain the use of the ``AggregatorReporter`` to compute the headroom and the ``ProfitOrLossReporter`` to compute the cost of running a process [see `PR #825 <https://github.com/FlexMeasures/flexmeasures/pull/825>`_ and `PR #856 <https://github.com/FlexMeasures/flexmeasures/pull/856>`_]
* Updated admin dashboard for inspecting asynchronous tasks (scheduling, forecasting, reporting, etc.), and improved performance and security of the server by upgrading Flask and Flask extensions [see `PR #838 <https://github.com/FlexMeasures/flexmeasures/pull/838>`_]
* Script to update dependencies across supported Python versions [see `PR #843 <https://github.com/FlexMeasures/flexmeasures/pull/843>`_]
* Test all supported Python versions in our CI pipeline (GitHub Actions) [see `PR #847 <https://github.com/FlexMeasures/flexmeasures/pull/847>`_]
* Have our CI pipeline (GitHub Actions) build the Docker image and make a schedule [see `PR #800 <https://github.com/FlexMeasures/flexmeasures/pull/800>`_]
* Updated documentation on the consequences of setting the ``FLEXMEASURES_MODE`` config setting [see `PR #857 <https://github.com/FlexMeasures/flexmeasures/pull/857>`_]
* Implement cache-busting to avoid the need for users to hard refresh the browser when new JavaScript functionality is added to the :abbr:`UI (user interface)` in a new FlexMeasures version [see `PR #860 <https://github.com/FlexMeasures/flexmeasures/pull/860>`_]


v0.15.2 | October 2, 2023
============================

Bugfixes
-----------
* Fix infeasible problem due to incorrect parsing of soc units of the ``soc-minima`` and ``soc-maxima`` fields within the ``flex-model`` field [see `PR #864 <https://github.com/FlexMeasures/flexmeasures/pull/864>`_]


v0.15.1 | August 28, 2023
============================

Bugfixes
-----------
* Fix infeasible problem due to floating point error in :abbr:`SoC (state of charge)` targets [see `PR #832 <https://github.com/FlexMeasures/flexmeasures/pull/832>`_]
* Use the ``source`` to filter beliefs in the ``AggregatorReporter`` and fix the case of having multiple sources [see `PR #819 <https://github.com/FlexMeasures/flexmeasures/pull/819>`_]
* Disable HiGHS logs on the standard output when ``LOGGING_LEVEL=INFO`` [see `PR #824 <https://github.com/FlexMeasures/flexmeasures/pull/824>`_ and `PR #826 <https://github.com/FlexMeasures/flexmeasures/pull/826>`_]
* Fix showing sensor data on the asset page of public assets, and searching for annotations on public assets [see `PR #830 <https://github.com/FlexMeasures/flexmeasures/pull/830>`_]
* Make the command ``flexmeasures add schedule for-storage`` to pass the soc-target timestamp to the flex model as strings instead of ``pd.Timestamp`` [see `PR #834 <https://github.com/FlexMeasures/flexmeasures/pull/834>`_]


v0.15.0 | August 9, 2023
============================

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/015-process-scheduling-heatmap/>`__.


.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

.. warning:: Upgrading to this version requires installing the LP/MILP solver HiGHS using ``pip install highspy``.

.. warning:: If your server is running in play mode (``FLEXMEASURES_MODE = "play"``), users will be able to see sensor data from any account [see `PR #740 <https://www.github.com/FlexMeasures/flexmeasures/pull/740>`_].

New features
-------------
* Add ``ProcessScheduler`` class to optimize the starting time of processes one of the policies developed (``INFLEXIBLE``, ``SHIFTABLE`` and ``BREAKABLE``), accessible via the CLI command ``flexmeasures add schedule for-process`` [see `PR #729 <https://www.github.com/FlexMeasures/flexmeasures/pull/729>`_ and `PR #768 <https://www.github.com/FlexMeasures/flexmeasures/pull/768>`_]
* Users can select a new chart type (daily heatmap) on the sensor page of the UI, showing how sensor values are distributed over the time of day [see `PR #715 <https://www.github.com/FlexMeasures/flexmeasures/pull/715>`_]
* Added API endpoints `/sensors/<id>` (GET) for fetching a single sensor, `/sensors` (POST) for adding a sensor, `/sensors/<id>` (PATCH) for updating a sensor and `/sensors/<id>` (DELETE) for deleting a sensor [see `PR #759 <https://www.github.com/FlexMeasures/flexmeasures/pull/759>`_] and [see `PR #767 <https://www.github.com/FlexMeasures/flexmeasures/pull/767>`_] and [see `PR #773 <https://www.github.com/FlexMeasures/flexmeasures/pull/773>`_] and [see `PR #784 <https://www.github.com/FlexMeasures/flexmeasures/pull/784>`_]
* Users are warned in the UI on when the data they are seeing includes one or more :abbr:`DST (Daylight Saving Time)` transitions, and heatmaps (see previous feature) visualize these transitions intuitively [see `PR #723 <https://www.github.com/FlexMeasures/flexmeasures/pull/723>`_]
* Allow deleting multiple sensors with a single call to ``flexmeasures delete sensor`` by passing the ``--id`` option multiple times [see `PR #734 <https://www.github.com/FlexMeasures/flexmeasures/pull/734>`_]
* Make it a lot easier to read off the color legend on the asset page, especially when showing many sensors, as they will now be ordered from top to bottom in the same order as they appear in the chart (as defined in the ``sensors_to_show`` attribute), rather than alphabetically [see `PR #742 <https://www.github.com/FlexMeasures/flexmeasures/pull/742>`_]
* Users on FlexMeasures servers in play mode (``FLEXMEASURES_MODE = "play"``) can use the ``sensors_to_show`` attribute to show any sensor on their asset pages, rather than only sensors registered to assets in their own account or to public assets [see `PR #740 <https://www.github.com/FlexMeasures/flexmeasures/pull/740>`_]
* Having percentages within the [0, 100] domain is such a common use case that we now always include it in sensor charts with % units, making it easier to read off individual charts and also to compare across charts [see `PR #739 <https://www.github.com/FlexMeasures/flexmeasures/pull/739>`_]
* The ``DataSource`` table now allows storing arbitrary attributes as a JSON (without content validation), similar to the ``Sensor`` and ``GenericAsset`` tables [see `PR #750 <https://www.github.com/FlexMeasures/flexmeasures/pull/750>`_]
* Users will be able to see (e.g. in the UI) exactly which reporter created the report (saved as sensor data), and hosts will be able to identify exactly which configuration was used to create a given report [see `PR #751 <https://www.github.com/FlexMeasures/flexmeasures/pull/751>`_ and `PR #788 <https://www.github.com/FlexMeasures/flexmeasures/pull/788>`_]
* The CLI ``flexmeasures add report`` now allows passing ``config`` and ``parameters`` in YAML format as files or editable via the system's default editor [see `PR #752 <https://www.github.com/FlexMeasures/flexmeasures/pull/752>`_ and `PR #788 <https://www.github.com/FlexMeasures/flexmeasures/pull/788>`_]
* The CLI now allows to set lists and dicts as asset & sensor attributes (formerly only single values) [see `PR #762 <https://www.github.com/FlexMeasures/flexmeasures/pull/762>`_]

Bugfixes
-----------
* Add binary constraint to avoid energy leakages during periods with negative prices [see `PR #770 <https://www.github.com/FlexMeasures/flexmeasures/pull/770>`_]

Infrastructure / Support
----------------------
* Add support for profiling Flask API calls using ``pyinstrument`` (if installed). Can be enabled by setting the environment variable ``FLEXMEASURES_PROFILE_REQUESTS`` to ``True`` [see `PR #722 <https://www.github.com/FlexMeasures/flexmeasures/pull/722>`_]
* The endpoint `[POST] /health/ready <api/v3_0.html#get--api-v3_0-health-ready>`_ returns the status of the Redis connection, if configured [see `PR #699 <https://www.github.com/FlexMeasures/flexmeasures/pull/699>`_]
* Document the ``device_scheduler`` linear program [see `PR #764 <https://www.github.com/FlexMeasures/flexmeasures/pull/764>`_]
* Add support for `HiGHS <https://highs.dev/>`_ solver [see `PR #766 <https://www.github.com/FlexMeasures/flexmeasures/pull/766>`_]
* Add support for installing FlexMeasures under Python 3.11 [see `PR #771 <https://www.github.com/FlexMeasures/flexmeasures/pull/771>`_]
* Start keeping sets of pinned requirements per supported Python version, which also fixes recent Docker build problem [see `PR #776 <https://www.github.com/FlexMeasures/flexmeasures/pull/776>`_]
* Removed obsolete code dealing with deprecated data models (e.g. assets, markets and weather sensors), and sunset the fm0 scheme for entity addresses [see `PR #695 <https://www.github.com/FlexMeasures/flexmeasures/pull/695>`_ and `project 11 <https://www.github.com/FlexMeasures/flexmeasures/projects/11>`_]


v0.14.3 | October 2, 2023
============================

Bugfixes
-----------
* Fix infeasible problem due to incorrect parsing of soc units of the ``soc-minima`` and ``soc-maxima`` fields within the ``flex-model`` field [see `PR #864 <https://github.com/FlexMeasures/flexmeasures/pull/864>`_]


v0.14.2 | July 25, 2023
============================

Bugfixes
-----------
* The error handling for infeasible constraints in ``storage.py`` was given too many arguments, which caused the response from the API to be unhelpful when a schedule was requested with infeasible constraints [see `PR #758 <https://github.com/FlexMeasures/flexmeasures/pull/758>`_]


v0.14.1 | June 26, 2023
============================

Bugfixes
-----------
* Relax constraint validation of ``StorageScheduler`` to accommodate violations caused by floating point precision [see `PR #731 <https://www.github.com/FlexMeasures/flexmeasures/pull/731>`_]
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
* Allow setting multiple :abbr:`SoC (state of charge)` maxima and minima constraints for the ``StorageScheduler``, using the new ``soc-minima`` and ``soc-maxima`` fields when calling `/sensors/<id>/schedules/trigger` (POST) through the API (within the ``flex-model`` field) [see `PR #680 <https://www.github.com/FlexMeasures/flexmeasures/pull/680>`_]
* New CLI command ``flexmeasures add report`` to calculate a custom report from sensor data and save the results to the database, with the option to export them to a CSV or Excel file [see `PR #659 <https://www.github.com/FlexMeasures/flexmeasures/pull/659>`_]
* New CLI commands ``flexmeasures show reporters`` and ``flexmeasures show schedulers`` to list available reporters and schedulers, respectively, including any defined in registered plugins [see `PR #686 <https://www.github.com/FlexMeasures/flexmeasures/pull/686>`_ and `PR #708 <https://github.com/FlexMeasures/flexmeasures/pull/708>`_]
* Allow creating public assets through the CLI, which are available to all users [see `PR #727 <https://github.com/FlexMeasures/flexmeasures/pull/727>`_]

Bugfixes
-----------
* Fix charts not always loading over https in secured scenarios [see `PR #716 <https://www.github.com/FlexMeasures/flexmeasures/pull/716>`_]

Infrastructure / Support
----------------------
* Introduction of the classes ``Reporter``, ``PandasReporter`` and ``AggregatorReporter`` to help customize your own reporter functions (experimental) [see `PR #641 <https://www.github.com/FlexMeasures/flexmeasures/pull/641>`_ and `PR #712 <https://www.github.com/FlexMeasures/flexmeasures/pull/712>`_]
* The setting ``FLEXMEASURES_PLUGINS`` can be set as environment variable now (as a comma-separated list) [see `PR #660 <https://www.github.com/FlexMeasures/flexmeasures/pull/660>`_]
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
* ``@deprecated`` not returning the output of the decorated function [see `PR #678 <https://www.github.com/FlexMeasures/flexmeasures/pull/678>`_]


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
* Overlay charts (e.g. power profiles) on the asset page using the ``sensors_to_show`` attribute, and distinguish plots by source (different trace), sensor (different color) and source type (different stroke dash) [see `PR #534 <https://www.github.com/FlexMeasures/flexmeasures/pull/534>`_]
* The ``FLEXMEASURES_MAX_PLANNING_HORIZON`` config setting can also be set as an integer number of planning steps rather than just as a fixed duration, which makes it possible to schedule further ahead in coarser time steps [see `PR #583 <https://www.github.com/FlexMeasures/flexmeasures/pull/583>`_]
* Different text styles for CLI output for errors, warnings or success messages [see `PR #609 <https://www.github.com/FlexMeasures/flexmeasures/pull/609>`_]
* Added API endpoints and webpages `/accounts` and `/accounts/<id>` to list accounts and show an overview of the assets, users and account roles of an account [see `PR #605 <https://github.com/FlexMeasures/flexmeasures/pull/605>`_]
* Avoid redundantly recomputing jobs that are triggered without a relevant state change, where the ``FLEXMEASURES_JOB_CACHE_TTL`` config setting defines the time in which the jobs with the same arguments are not being recomputed [see `PR #616 <https://www.github.com/FlexMeasures/flexmeasures/pull/616>`_]

Bugfixes
-----------
* Fix copy button on tutorials and other documentation, so that only commands are copied and no output or comments [see `PR #636 <https://www.github.com/FlexMeasures/flexmeasures/pull/636>`_]
* GET /api/v3_0/assets/public should ask for token authentication and not forward to login page [see `PR #649 <https://www.github.com/FlexMeasures/flexmeasures/pull/649>`_]

Infrastructure / Support
----------------------
* Support blackout tests for sunset API versions [see `PR #651 <https://www.github.com/FlexMeasures/flexmeasures/pull/651>`_]
* Sunset API versions 1.0, 1.1, 1.2, 1.3 and 2.0 [see `PR #650 <https://www.github.com/FlexMeasures/flexmeasures/pull/650>`_]
* Sunset several API fields for `/sensors/<id>/schedules/trigger` (POST) that have moved into the ``flex-model`` or ``flex-context`` fields [see `PR #580 <https://www.github.com/FlexMeasures/flexmeasures/pull/580>`_]
* Fix broken ``make show-data-model`` command [see `PR #638 <https://www.github.com/FlexMeasures/flexmeasures/pull/638>`_]
* Bash script for a clean database to run toy-tutorial by using ``make clean-db db_name=database_name`` command [see `PR #640 <https://github.com/FlexMeasures/flexmeasures/pull/640>`_]


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
* Fix ``flexmeasures db-ops dump`` and ``flexmeasures db-ops restore`` not working in docker containers [see `PR #530 <https://www.github.com/FlexMeasures/flexmeasures/pull/530>`_] and incorrectly reporting a success when ``pg_dump`` and ``pg_restore`` are not installed [see `PR #526 <https://www.github.com/FlexMeasures/flexmeasures/pull/526>`_]
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
* Fix scheduling with imperfect efficiencies, which resulted in exceeding the device's lower :abbr:`SoC (state of charge)` limit [see `PR #520 <https://www.github.com/FlexMeasures/flexmeasures/pull/520>`_]
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
* Avoid formatting ``datetime.timedelta`` durations as nominal ISO durations [see `PR #459 <https://www.github.com/FlexMeasures/flexmeasures/pull/459>`_]
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
* Add CLI command to delete an asset, with its sensors and data [see `PR #395 <https://www.github.com/FlexMeasures/flexmeasures/pull/395>`_]
* Add CLI command to edit/add an attribute on an asset or sensor [see `PR #380 <https://www.github.com/FlexMeasures/flexmeasures/pull/380>`_]
* Add CLI command to add a toy account for tutorials and trying things [see `PR #368 <https://www.github.com/FlexMeasures/flexmeasures/pull/368>`_]
* Add CLI command to create a charging schedule [see `PR #372 <https://www.github.com/FlexMeasures/flexmeasures/pull/372>`_]
* Support for percent (%) and permille (‰) sensor units [see `PR #359 <https://www.github.com/FlexMeasures/flexmeasures/pull/359>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/090-cli-developer-power/>`__.

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
.. note:: v0.8.0 is doing much of the work we need to do to move to the new data model (see :ref:`note_on_datamodel_transition`). We hope to keep the migration steps for users very limited. One thing you'll notice is that we are copying over existing data to the new model (which will be kept in sync) with the ``db upgrade`` command (see warning above), which can take a few minutes.

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
* Support the new asset model (which describes the organisational structure, rather than sensors and data) in UI and API - until the transition to our new data model is completed, the new API for assets is at `/api/dev/generic_assets` [see `PR #251 <https://www.github.com/FlexMeasures/flexmeasures/pull/251>`_ and `PR #290 <https://www.github.com/FlexMeasures/flexmeasures/pulls/290>`_]
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
* Set a logo for the top left corner with the new ``FLEXMEASURES_MENU_LOGO_PATH`` setting [see `PR #184 <https://www.github.com/FlexMeasures/flexmeasures/pull/184>`_]
* Add an extra style-sheet which applies to all pages with the new ``FLEXMEASURES_EXTRA_CSS_PATH`` setting [see `PR #185 <https://www.github.com/FlexMeasures/flexmeasures/pull/185>`_]
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
* FlexMeasures plugins can be Python packages now, and we provide `a cookie-cutter template <https://github.com/FlexMeasures/flexmeasures-plugin-template>`_ for this approach [see `PR #182 <https://www.github.com/FlexMeasures/flexmeasures/pull/182>`_]
* Set default timezone for new users using the ``FLEXMEASURES_TIMEZONE`` config setting [see `PR #190 <https://www.github.com/FlexMeasures/flexmeasures/pull/190>`_]
* To avoid databases from filling up with irrelevant information, only beliefs data representing *changed beliefs are saved*, and *unchanged beliefs are dropped* [see `PR #194 <https://www.github.com/FlexMeasures/flexmeasures/pull/194>`_]
* Monitored CLI tasks can get better names for identification [see `PR #193 <https://www.github.com/FlexMeasures/flexmeasures/pull/193>`_]
* Less custom logfile location, document logging for devs [see `PR #196 <https://www.github.com/FlexMeasures/flexmeasures/pull/196>`_]
* Keep forecasting and scheduling jobs in the queues for only up to one day [see `PR #198 <https://www.github.com/FlexMeasures/flexmeasures/pull/198>`_]


v0.6.1 | October 23, 2021
===========================

Bugfixes
-----------
* Fix (dev) CLI command for adding a ``GenericAssetType`` [see `PR #173 <https://www.github.com/FlexMeasures/flexmeasures/pull/173>`_]
* Fix (dev) CLI command for adding a ``Sensor`` [see `PR #176 <https://www.github.com/FlexMeasures/flexmeasures/pull/176>`_]
* Fix missing conversion of data source names and ids to ``DataSource`` objects [see `PR #178 <https://www.github.com/FlexMeasures/flexmeasures/pull/178>`_]
* Fix GetDeviceMessage to ensure chronological ordering of values [see `PR #216 <https://www.github.com/FlexMeasures/flexmeasures/pull/216>`_]


v0.6.0 | September 3, 2021
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).
             In case you are using experimental developer features and have previously set up sensors, be sure to check out the upgrade instructions in `PR #157 <https://github.com/FlexMeasures/flexmeasures/pull/157>`_. Furthermore, if you want to create custom user/account relationships while upgrading (otherwise the upgrade script creates accounts based on email domains), check out the upgrade instructions in `PR #159 <https://github.com/FlexMeasures/flexmeasures/pull/159>`_. If you want to use both of these custom upgrade features, do the upgrade in two steps. First, as described in PR 157 and upgrading up to revision ``b6d49ed7cceb``, then as described in PR 159 for the rest.

.. warning:: The config setting ``FLEXMEASURES_LISTED_VIEWS`` has been renamed to ``FLEXMEASURES_MENU_LISTED_VIEWS``.

.. warning:: Plugins now need to set their version on their module rather than on their blueprint. See the `documentation for writing plugins <https://flexmeasures.readthedocs.io/en/v0.6.0/dev/plugins.html>`_.

New features
-----------
* Multi-tenancy: Supporting multiple customers per FlexMeasures server, by introducing the ``Account`` concept, where accounts have users and assets associated [see `PR #159 <https://www.github.com/FlexMeasures/flexmeasures/pull/159>`_ and `PR #163 <https://www.github.com/FlexMeasures/flexmeasures/pull/163>`_]
* In the UI, the root view ("/"), the platform name and the visible menu items can now be more tightly controlled (per account roles of the current user) [see also `PR #163 <https://www.github.com/FlexMeasures/flexmeasures/pull/163>`_]
* Analytics view offers grouping of all assets by location [see `PR #148 <https://www.github.com/FlexMeasures/flexmeasures/pull/148>`_]
* Add (experimental) endpoint to post sensor data for any sensor. Also supports our ongoing integration with data internally represented using the `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib [see `PR #147 <https://www.github.com/FlexMeasures/flexmeasures/pull/147>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v060-multi-tenancy-error-monitoring/>`__.

Infrastructure / Support
----------------------
* Add possibility to send errors to Sentry [see `PR #143 <https://www.github.com/FlexMeasures/flexmeasures/pull/143>`_]
* Add CLI task to monitor if tasks ran successfully and recently enough [see `PR #146 <https://www.github.com/FlexMeasures/flexmeasures/pull/146>`_]
* Document how to use a custom favicon in plugins [see `PR #152 <https://www.github.com/FlexMeasures/flexmeasures/pull/152>`_]
* Allow plugins to register multiple Flask blueprints [see `PR #171 <https://www.github.com/FlexMeasures/flexmeasures/pull/171>`_]
* Continue experimental integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib: link multiple sensors to a single asset [see `PR #157 <https://github.com/FlexMeasures/flexmeasures/pull/157>`_]
* The experimental parts of the data model can now be visualised, as well, via ``make show-data-model`` (add the ``--dev`` option in ``Makefile``) [also in `PR #157 <https://github.com/FlexMeasures/flexmeasures/pull/157>`_]


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
* Add ``time_utils.get_recent_clock_time_window`` function [see `PR #135 <https://www.github.com/FlexMeasures/flexmeasures/pull/135>`_]


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
* Begin experimental integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib: ``Sensor`` data as ``TimedBelief`` objects [see `PR #79 <https://www.github.com/FlexMeasures/flexmeasures/pull/79>`_ and `PR #99 <https://github.com/FlexMeasures/flexmeasures/pull/99>`_]
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

