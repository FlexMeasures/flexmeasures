**********************
FlexMeasures Changelog
**********************


v0.2.3 | February 27, 2021
===========================

New features
------------
* Power charts available via the API [see `PR #39 <http://www.github.com/SeitaBV/flexmeasures/pull/39>`__]
* User management via the API [see `PR #25 <http://www.github.com/SeitaBV/flexmeasures/pull/25>`__]
* Better visibility of asset icons on maps [see `PR #30 <http://www.github.com/SeitaBV/flexmeasures/pull/30>`__]

.. Note:: Read more on these features on `the FlexMeasures blog <https://flexmeasures.io/user-management-via-api/>`__.

Bugfixes
--------
* Fix maps on new asset page (update MapBox lib) [see `PR #27 <http://www.github.com/SeitaBV/flexmeasures/pull/27>`__]
* Some asset links were broken [see `PR #20 <http://www.github.com/SeitaBV/flexmeasures/pull/20>`__]
* Password reset link on account page was broken [see `PR #23 <http://www.github.com/SeitaBV/flexmeasures/pull/23>`__]
 

Infrastructure/Support
----------------------
* CI via Github Actions [see `PR #1 <http://www.github.com/SeitaBV/flexmeasures/pull/1>`__]
* Integration with `timely beliefs <https://github.com/SeitaBV/timely-beliefs>`__ lib: Sensors [see `PR #13 <http://www.github.com/SeitaBV/flexmeasures/pull/13>`__]
* Apache 2.0 license [see `PR #16 <http://www.github.com/SeitaBV/flexmeasures/pull/16>`__]
* Load js & css from CDN [see `PR #21 <http://www.github.com/SeitaBV/flexmeasures/pull/21>`__]
* Start using marshmallow for input validation, also introducing ``HTTP status 422`` in the API [see `PR #25 <http://www.github.com/SeitaBV/flexmeasures/pull/25>`__]
* Replace ``solarpy`` with ``pvlib`` (due to license conflict) [see `PR #16 <http://www.github.com/SeitaBV/flexmeasures/pull/16>`__]
* Stop supporting the creation of new users on asset creation (to reduce complexity) [see `PR #36 <http://www.github.com/SeitaBV/flexmeasures/pull/36>`__]

