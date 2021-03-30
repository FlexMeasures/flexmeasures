.. _control:

*****************
Flexibility opportunities
*****************

Flexibility opportunities have commercial value that users can valorise on.
When FlexMeasures has identified commercial value of flexibility, the user is suggested to act on it.
This might happen in an automated fashion (scripts reading out suggested schedules from the FlexMeasures API and implementing them to local operations if possible) or manually (operators agreeing with the opportunities identified by FlexMeasures and acting on the suggested schedules).

For this latter case, in the Flexibility opportunities web-page (a yet-to-be designed UI feature discussed below), FlexMeasures could show all flexibility opportunities that the user can act on for a selected time window.

.. contents::
    :local:
    :depth: 1


Visualisation of opportunities
========================

Visualising flexibility opportunities and their effects is not straightforward.

Here is a potential UX design which we have not implemented yet:

.. image:: https://github.com/SeitaBV/screenshots/raw/main/screenshot_control.png
    :align: center
..    :scale: 40%

Flexibility opportunities cause changes to the power profile of an asset.
Such effects could be taken into account by FlexMeasures and shown to the user, e.g. as a part of expected value calculations and power profile forecasts.

An example how this could look like is below.
The operator can select flexibility opportunities which have a value attached to them and see the effects on the power profile in a visual manner.

Listed flexibility opportunities include previously realised opportunities and currently offered opportunities.
Currently offered opportunties are presented as an order book, where they are sorted according to their commercial value.

Of course, depending on the time window selection and constraints set by the asset owner, the effects of an opportunity may partially take place outside of the selected time window.