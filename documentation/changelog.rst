**********************
FlexMeasures Changelog
**********************


v0.7.1 | November 08, 2021
===========================

Bugfixes
-----------
* Fix device messages, which were mixing up older and more recent schedules [see `PR #231 <http://www.github.com/SeitaBV/flexmeasures/pull/231>`_]


v0.7.0 | October 26, 2021
===========================

.. warning:: The config setting ``FLEXMEASURES_PLUGIN_PATHS`` has been renamed to ``FLEXMEASURES_PLUGINS``. The old name still works but is deprecated.

New features
-----------
* Set a logo for the top left corner with the new FLEXMEASURES_MENU_LOGO_PATH setting [see `PR #184 <http://www.github.com/SeitaBV/flexmeasures/pull/184>`_]
* Add an extra style-sheet which applies to all pages with the new FLEXMEASURES_EXTRA_CSS_PATH setting [see `PR #185 <http://www.github.com/SeitaBV/flexmeasures/pull/185>`_]
* Data sources can be further distinguished by what model (and version) they ran [see `PR #215 <http://www.github.com/SeitaBV/flexmeasures/pull/215>`_]
* Enable plugins to automate tests with app context [see `PR #220 <http://www.github.com/SeitaBV/flexmeasures/pull/220>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/070-professional-plugins/>`__.

Bugfixes
-----------
* Fix users resetting their own password [see `PR #195 <http://www.github.com/SeitaBV/flexmeasures/pull/195>`_]
* Fix scheduling for heterogeneous settings, for instance, involving sensors with different time zones and/or resolutions [see `PR #207 <http://www.github.com/SeitaBV/flexmeasures/pull/207>`_]
* Fix ``sensors/<id>/chart`` view [see `PR #223 <http://www.github.com/SeitaBV/flexmeasures/pull/223>`_]

Infrastructure / Support
----------------------
* FlexMeasures plugins can be Python packages now. We provide `a cookie-cutter template <https://github.com/SeitaBV/flexmeasures-plugin-template>`_ for this approach. [see `PR #182 <http://www.github.com/SeitaBV/flexmeasures/pull/182>`_]
* Set default timezone for new users using the FLEXMEASURES_TIMEZONE config setting [see `PR #190 <http://www.github.com/SeitaBV/flexmeasures/pull/190>`_]
* To avoid databases from filling up with irrelevant information, only beliefs data representing *changed beliefs are saved*, and *unchanged beliefs are dropped* [see `PR #194 <http://www.github.com/SeitaBV/flexmeasures/pull/194>`_]
* Monitored CLI tasks can get better names for identification [see `PR #193 <http://www.github.com/SeitaBV/flexmeasures/pull/193>`_]
* Less custom logfile location, document logging for devs [see `PR #196 <http://www.github.com/SeitaBV/flexmeasures/pull/196>`_]
* Keep forecasting and scheduling jobs in the queues for only up to one day [see `PR #198 <http://www.github.com/SeitaBV/flexmeasures/pull/198>`_]


v0.6.1 | October 23, 2021
===========================

New features
-----------

Bugfixes
-----------
* Fix (dev) CLI command for adding a GenericAssetType [see `PR #173 <http://www.github.com/SeitaBV/flexmeasures/pull/173>`_]
* Fix (dev) CLI command for adding a Sensor [see `PR #176 <http://www.github.com/SeitaBV/flexmeasures/pull/176>`_]
* Fix missing conversion of data source names and ids to DataSource objects [see `PR #178 <http://www.github.com/SeitaBV/flexmeasures/pull/178>`_]
* Fix GetDeviceMessage to ensure chronological ordering of values [see `PR #216 <http://www.github.com/SeitaBV/flexmeasures/pull/216>`_]

Infrastructure / Support
----------------------


v0.6.0 | September 3, 2021
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).
             In case you are using experimental developer features and have previously set up sensors, be sure to check out the upgrade instructions in `PR #157 <https://github.com/SeitaBV/flexmeasures/pull/157>`_. Furthermore, if you want to create custom user/account relationships while upgrading (otherwise the upgrade script creates accounts based on email domains), check out the upgrade instructions in `PR #159 <https://github.com/SeitaBV/flexmeasures/pull/159>`_. If you want to use both of these custom upgrade features, do the upgrade in two steps. First, as described in PR 157 and upgrading up to revision b6d49ed7cceb, then as described in PR 159 for the rest.

.. warning:: The config setting ``FLEXMEASURES_LISTED_VIEWS`` has been renamed to ``FLEXMEASURES_MENU_LISTED_VIEWS``.

.. warning:: Plugins now need to set their version on their module rather than on their blueprint. See the `documentation for writing plugins <https://flexmeasures.readthedocs.io/en/v0.6.0/dev/plugins.html>`_.

New features
-----------
* Multi-tenancy: Supporting multiple customers per FlexMeasures server, by introducing the `Account` concept. Accounts have users and assets associated. [see `PR #159 <http://www.github.com/SeitaBV/flexmeasures/pull/159>`_ and `PR #163 <http://www.github.com/SeitaBV/flexmeasures/pull/163>`_]
* In the UI, the root view ("/"), the platform name and the visible menu items can now be more tightly controlled (per account roles of the current user) [see also `PR #163 <http://www.github.com/SeitaBV/flexmeasures/pull/163>`_]
* Analytics view offers grouping of all assets by location [see `PR #148 <http://www.github.com/SeitaBV/flexmeasures/pull/148>`_]
* Add (experimental) endpoint to post sensor data for any sensor. Also supports our ongoing integration with data internally represented using the `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib [see `PR #147 <http://www.github.com/SeitaBV/flexmeasures/pull/147>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v060-multi-tenancy-error-monitoring/>`__.

Bugfixes
-----------

Infrastructure / Support
----------------------
* Add possibility to send errors to Sentry [see `PR #143 <http://www.github.com/SeitaBV/flexmeasures/pull/143>`_]
* Add CLI task to monitor if tasks ran successfully and recently enough [see `PR #146 <http://www.github.com/SeitaBV/flexmeasures/pull/146>`_]
* Document how to use a custom favicon in plugins [see `PR #152 <http://www.github.com/SeitaBV/flexmeasures/pull/152>`_]
* Allow plugins to register multiple Flask blueprints [see `PR #171 <http://www.github.com/SeitaBV/flexmeasures/pull/171>`_]
* Continue experimental integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib: link multiple sensors to a single asset [see `PR #157 <https://github.com/SeitaBV/flexmeasures/pull/157>`_]
* The experimental parts of the data model can now be visualised, as well, via `make show-data-model` (add the --dev option in Makefile) [also in `PR #157 <https://github.com/SeitaBV/flexmeasures/pull/157>`_]



v0.5.0 | June 7, 2021
===========================

.. warning:: If you retrieve weather forecasts through FlexMeasures: we had to switch to OpenWeatherMap, as Dark Sky is closing. This requires an update to config variables ― the new setting is called ``OPENWEATHERMAP_API_KEY``.

New features
-----------
* Allow plugins to overwrite UI routes and customise the teaser on the login form [see `PR #106 <http://www.github.com/SeitaBV/flexmeasures/pull/106>`_]
* Allow plugins to customise the copyright notice and credits in the UI footer [see `PR #123 <http://www.github.com/SeitaBV/flexmeasures/pull/123>`_]
* Display loaded plugins in footer and support plugin versioning [see `PR #139 <http://www.github.com/SeitaBV/flexmeasures/pull/139>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v050-openweathermap-plugin-customisation/>`__.

Bugfixes
-----------
* Fix last login date display in user list [see `PR #133 <http://www.github.com/SeitaBV/flexmeasures/pull/133>`_]
* Choose better forecasting horizons when weather data is posted [see `PR #131 <http://www.github.com/SeitaBV/flexmeasures/pull/131>`_]

Infrastructure / Support
----------------------
* Add tutorials on how to add and read data from FlexMeasures via its API [see `PR #130 <http://www.github.com/SeitaBV/flexmeasures/pull/130>`_]
* For weather forecasts, switch from Dark Sky (closed from Aug 1, 2021) to OpenWeatherMap API [see `PR #113 <http://www.github.com/SeitaBV/flexmeasures/pull/113>`_]
* Entity address improvements: add new id-based `fm1` scheme, better documentation and more validation support of entity addresses [see `PR #81 <http://www.github.com/SeitaBV/flexmeasures/pull/81>`_]
* Re-use the database between automated tests, if possible. This shaves 2/3rd off of the time it takes for the FlexMeasures test suite to run [see `PR #115 <http://www.github.com/SeitaBV/flexmeasures/pull/115>`_]
* Make assets use MW as their default unit and enforce that in CLI, as well (API already did) [see `PR #108 <http://www.github.com/SeitaBV/flexmeasures/pull/108>`_]
* Let CLI package and plugins use Marshmallow Field definitions [see `PR #125 <http://www.github.com/SeitaBV/flexmeasures/pull/125>`_]
* add time_utils.get_recent_clock_time_window() function [see `PR #135 <http://www.github.com/SeitaBV/flexmeasures/pull/135>`_]



v0.4.1 | May 7, 2021
===========================

Bugfixes
-----------
* Fix regression when editing assets in the UI [see `PR #122 <http://www.github.com/SeitaBV/flexmeasures/pull/122>`_]
* Fixed a regression that stopped asset, market and sensor selection from working [see `PR #117 <http://www.github.com/SeitaBV/flexmeasures/pull/117>`_]
* Prevent logging out user when clearing the session [see `PR #112 <http://www.github.com/SeitaBV/flexmeasures/pull/112>`_]
* Prevent user type data source to be created without setting a user [see `PR #111 <https://github.com/SeitaBV/flexmeasures/pull/111>`_]

v0.4.0 | April 29, 2021
===========================

.. warning:: Upgrading to this version requires running ``flexmeasures db upgrade`` (you can create a backup first with ``flexmeasures db-ops dump``).

New features
-----------
* Allow for views and CLI functions to come from plugins [see also `PR #91 <https://github.com/SeitaBV/flexmeasures/pull/91>`_]
* Configure the UI menu with ``FLEXMEASURES_LISTED_VIEWS`` [see `PR #91 <https://github.com/SeitaBV/flexmeasures/pull/91>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v040-plugin-support/>`__.

Bugfixes
-----------
* Asset edit form displayed wrong error message. Also enabled the asset edit form to display the invalid user input back to the user [see `PR #93 <http://www.github.com/SeitaBV/flexmeasures/pull/93>`_]

Infrastructure / Support
----------------------
* Updated dependencies, including Flask-Security-Too [see `PR #82 <http://www.github.com/SeitaBV/flexmeasures/pull/82>`_]
* Improved documentation after user feedback [see `PR #97 <http://www.github.com/SeitaBV/flexmeasures/pull/97>`_]
* Begin experimental integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`_ lib: Sensor data as TimedBeliefs [see `PR #79 <http://www.github.com/SeitaBV/flexmeasures/pull/79>`_ and `PR #99 <https://github.com/SeitaBV/flexmeasures/pull/99>`_]
* Add sensors with CLI command currently meant for developers only [see `PR #83 <https://github.com/SeitaBV/flexmeasures/pull/83>`_]
* Add data (beliefs about sensor events) with CLI command currently meant for developers only [see `PR #85 <https://github.com/SeitaBV/flexmeasures/pull/85>`_ and `PR #103 <https://github.com/SeitaBV/flexmeasures/pull/103>`_]


v0.3.1 | April 9, 2021
===========================

Bugfixes
--------
* PostMeterData endpoint was broken in API v2.0 [see `PR #95 <http://www.github.com/SeitaBV/flexmeasures/pull/95>`_]


v0.3.0 | April 2, 2021
===========================

New features
-----------
* FlexMeasures can be installed with ``pip`` and its CLI commands can be run with ``flexmeasures`` [see `PR #54 <http://www.github.com/SeitaBV/flexmeasures/pull/54>`_]
* Optionally setting recording time when posting data [see `PR #41 <http://www.github.com/SeitaBV/flexmeasures/pull/41>`_]
* Add assets and weather sensors with CLI commands [see `PR #74 <https://github.com/SeitaBV/flexmeasures/pull/74>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v030-pip-install-cli-commands-belief-time-api/>`__.

Bugfixes
--------
* Show screenshots in documentation and add some missing content [see `PR #60 <http://www.github.com/SeitaBV/flexmeasures/pull/60>`_]
* Documentation listed 2.0 API endpoints twice [see `PR #59 <http://www.github.com/SeitaBV/flexmeasures/pull/59>`_]
* Better xrange and title if only schedules are plotted [see `PR #67 <http://www.github.com/SeitaBV/flexmeasures/pull/67>`_]
* User page did not list number of assets correctly [see `PR #64 <http://www.github.com/SeitaBV/flexmeasures/pull/64>`_]
* Missing *postPrognosis* endpoint for >1.0 API blueprints [part of `PR #41 <http://www.github.com/SeitaBV/flexmeasures/pull/41>`_]

Infrastructure / Support
----------------------
* Added concept pages to documentation [see `PR #65 <http://www.github.com/SeitaBV/flexmeasures/pull/65>`_]
* Dump and restore postgres database as CLI commands [see `PR #68 <https://github.com/SeitaBV/flexmeasures/pull/68>`_]
* Improved installation tutorial as part of [`PR #54 <http://www.github.com/SeitaBV/flexmeasures/pull/54>`_]
* Moved developer docs from Readmes into the main documentation  [see `PR #73 <https://github.com/SeitaBV/flexmeasures/pull/73>`_]
* Ensured unique sensor ids for all sensors [see `PR #70 <https://github.com/SeitaBV/flexmeasures/pull/70>`_ and (fix) `PR #77 <https://github.com/SeitaBV/flexmeasures/pull/77>`_]




v0.2.3 | February 27, 2021
===========================

New features
------------
* Power charts available via the API [see `PR #39 <http://www.github.com/SeitaBV/flexmeasures/pull/39>`_]
* User management via the API [see `PR #25 <http://www.github.com/SeitaBV/flexmeasures/pull/25>`_]
* Better visibility of asset icons on maps [see `PR #30 <http://www.github.com/SeitaBV/flexmeasures/pull/30>`_]

.. note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/v023-user-api-power-chart-api-better-icons/>`__.

Bugfixes
--------
* Fix maps on new asset page (update MapBox lib) [see `PR #27 <http://www.github.com/SeitaBV/flexmeasures/pull/27>`_]
* Some asset links were broken [see `PR #20 <http://www.github.com/SeitaBV/flexmeasures/pull/20>`_]
* Password reset link on account page was broken [see `PR #23 <http://www.github.com/SeitaBV/flexmeasures/pull/23>`_]
 

Infrastructure / Support
----------------------
* CI via Github Actions [see `PR #1 <http://www.github.com/SeitaBV/flexmeasures/pull/1>`_]
* Integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`__ lib: Sensors [see `PR #13 <http://www.github.com/SeitaBV/flexmeasures/pull/13>`_]
* Apache 2.0 license [see `PR #16 <http://www.github.com/SeitaBV/flexmeasures/pull/16>`_]
* Load js & css from CDN [see `PR #21 <http://www.github.com/SeitaBV/flexmeasures/pull/21>`_]
* Start using marshmallow for input validation, also introducing ``HTTP status 422`` in the API [see `PR #25 <http://www.github.com/SeitaBV/flexmeasures/pull/25>`_]
* Replace ``solarpy`` with ``pvlib`` (due to license conflict) [see `PR #16 <http://www.github.com/SeitaBV/flexmeasures/pull/16>`_]
* Stop supporting the creation of new users on asset creation (to reduce complexity) [see `PR #36 <http://www.github.com/SeitaBV/flexmeasures/pull/36>`_]

