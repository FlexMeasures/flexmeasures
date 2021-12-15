.. _portfolio:

******************
Portfolio overview
******************

The portfolio overview shows results and opportunities regarding the user's asset portfolio.
The view serves to get an overview over the portfolio's energy status and can be viewed with either
the consumption or the generation side aggregated.

In particular, the page contains:

.. contents::
    :local:
    :depth: 1


.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_portfolio.png
    :align: center
..    :scale: 40%


.. _portfolio_statements:

Statements about energy and flex activations
=======================================================

The financial statements separate the effects of energy consumption/production and flexible schedules over two tables.

Energy summary
-----------------------

The top table lists the effects of energy trading for each asset type in the user's portfolio.
Production and consumption values are total volumes within the selected time window.
[#f1]_

Costs and revenues are calculated based on the relevant market prices for the user within the selected time window.
A consumer will only have costs, while a prosumer may have both costs and revenues.
A supplier has revenues, since it sells energy to the other roles within FlexMeasures. 

Finally, the financial statements show the total profit or loss per asset type.


Market status
----------------------------------
.. note:: This feature is mocked for now.

The bottom table lists the effects of flexible schedules for each asset type in the user's portfolio.
Separate columns are stated for each type of scheduled deviation from the status quo, e.g. curtailment and shifting (see :ref:`flexibility_types`), with relevant total volumes within the selected time window.
[#f1]_

Costs and revenues are calculated based on the following internal method for profit sharing:
Asset owners that follow flexible schedules via the platform will generate revenues.
Suppliers that follow flexible schedules via the platform will generate both costs and revenues, where the revenues come from interacting with external markets.
Finally, the financial statements show the total profit or loss per asset.

.. rubric:: Footnotes

.. [#f1] For time windows that include future time slots, future values are based on forecasts.


.. _portfolio_power_profile:

Power profile measurements and forecasts
========================================

The power profile shows total production and consumption over the selected time window.
A switch allows the user to view the contribution of each asset type to either total as a stacked plot.
Past time slots show measurement data, whereas future time slots show forecasts.
When suggested changes exist in flexible schedules during the selected time window, the plot is overlaid with highlights (see :ref:`portfolio_flexibility_opportunities` ).


.. _portfolio_flexibility_effects:

Changes to the power profile due to flexible schedules
=====================================================

A crucial goal of FlexMeasures is to visualise the opportunities within flexible schedules.
This goal is not yet completely realised, but we show a mock here of how this could like when realised: 

Just below the power profile, the net effect of flexible schedules that have previously been computed by FlexMeasures is plotted.
The profile indicates the change in power resulting from schedules that are planned in the future, as well as from schedules that had been planned in the past.
Positive values indicate an increase in production or a decrease in consumption, both of which result in an increased load on the network.
For short-term changes in power due to activation of flexibility, this is sometimes called up-regulation.
Negative values indicate a decrease in production or an increase in consumption, which result in a decreased load on the network (down-regulation).
When flexibility opportunities exist in the selected time window, the plot is overlaid with highlights (see :ref:`portfolio_flexibility_opportunities` ).


.. _portfolio_flexibility_opportunities:

Opportunities to valorise on flexibility 
==============================================

When flexibility opportunities exist in the selected time window, plots are overlaid with highlights indicating time slots
in which flexible scheduling adjustments can be taken in the future or were missed in the past.
The default time window (the next 24 hours) shows immediately upcoming opportunities to valorise on flexibility opportunities.
The user could learn more about identified opportunities on a yet-to-be-developed view which goes further into details.
