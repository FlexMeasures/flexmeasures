**********************
FlexMeasures Changelog
**********************


v0.4.0 | April 29, 2021
===========================

New features
-----------
* Configure the UI menu with ``FLEXMEASURES_LISTED_VIEWS`` [see `PR #91 <https://github.com/SeitaBV/flexmeasures/pull/91>`_]
* Allow for views and CLI functions to come from plugins [see also `PR #91 <https://github.com/SeitaBV/flexmeasures/pull/91>`_]

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

