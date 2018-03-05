.. _portfolio:

******************
Portfolio overview
******************

The portfolio overview shows results and opportunities regarding the user's asset portfolio.
The view serves to quickly identify upcoming opportunities to valorise on balancing actions.
In particular, the page contains:

.. contents::
    :local:
    :depth: 1


.. _portfolio_financial_statements:

Financial statements about energy and balancing actions
=======================================================

The financial statements separate the effects of energy consumption/production and balancing actions over two tables.

Statements about energy
-----------------------

The top table lists the effects of energy trading for each asset type in the user's portfolio.
Production and consumption values are total volumes within the selected time window.
[#f1]_

Costs and revenues are calculated based on the relevant market prices for the user within the selected time window.
A consumer will only have costs, while a prosumer may have both costs and revenues.
A supplier always has both costs and revenues, since it trades energy both with its customers and with external markets.
Finally, the financial statements show the total profit or loss per asset.

Statements about balancing actions
----------------------------------

The bottom table lists the effects of balancing actions for each asset type in the user's portfolio.
Separate columns are stated for each type of action, e.g. curtailing and shifting, with relevant total volumes within the selected time window.
[#f1]_

Costs and revenues are calculated based on the internal method for profit sharing.
Asset owners that provide balancing actions via the platform will generate revenues.
Suppliers that order balancing action via the platform will generate both costs and revenues, where the revenues come from interacting with external markets.
Finally, the financial statements show the total profit or loss per asset.

.. rubric:: Footnotes

.. [#f1] For time windows that include future time slots, future values are based on forecasts.


.. _portfolio_power_profile:

Power profile measurements and forecasts
========================================

The power profile shows total production and consumption over the selected time window.
A switch allows the user to view the contribution of each asset type to either total as a stacked plot.
Past time slots show measurement data, whereas future time slots show forecasts.
When balancing opportunities exist in the selected time window, the plot is overlaid with highlights (see :ref:`portfolio_balancing_opportunities` ).


.. _portfolio_balancing_effects:

Changes to the power profile due to balancing actions
=====================================================

Just below the power profile, the net effect of balancing actions that have previously been ordered is plotted.
The profile indicates the change in power resulting from actions that are planned in the future, and from actions that had been planned in the past.
Positive values indicate an increase in production or a decrease in consumption, both of which result in an increased load on the network.
For short-term balancing actions, this is sometimes called up-regulation.
Negative values indicate a decrease in production or an increase in consumption, which result in a decreased load on the network (down-regulation).
When balancing opportunities exist in the selected time window, the plot is overlaid with highlights (see :ref:`portfolio_balancing_opportunities` ).


.. _portfolio_balancing_opportunities:

Opportunities to valorise on balancing actions
==============================================

When balancing opportunities exist in the selected time window, plots are overlaid with highlights indicating time slots in which balancing actions can be taken in the future or were missed in the past.
The default time window (the next 24 hours) shows immediately upcoming opportunities to valorise on balancing actions.
The user can follow up on identified opportunities by taking a balancing action on the :ref:`control` page.


.. image:: ../img/screenshot_portfolio.png
    :target: ../../../../portfolio
    :align: center
..    :scale: 40%

.. image:: ../img/screenshot_portfolio-prosumer-mock-vehicles.png
    :target: ../../../../portfolio?prosumer_mock=vehicles
    :align: center
..    :scale: 40%


