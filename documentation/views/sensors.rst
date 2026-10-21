.. _view_sensors:

*********************
Sensors
*********************


Each sensor also has its own page:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_sensor.png
    :align: center
..    :scale: 40%

|
|

Next to line plots, data can sometimes be more usefully displayed as heatmaps.
Heatmaps are great ways to spot the hotspots of activity. Usually heatmaps are actually geographical maps. In our context, the most interesting background is time ― so we'd like to see activity hotspots on a map of time intervals.

We chose the "time map" of weekdays. From our experience, this is where you see the most interesting activity hotspots at a glance. For instance, that mornings often experience peaks. Or that Tuesday afternoons have low energy use, for some reason.

Here is what it looks like for one week of temperature data:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/heatmap-week-temperature.png
    :align: center
    
It's easy to see which days had milder temperatures.

And here are 4 days of (dis)-charging patterns in Seita's V2GLiberty project:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/heatmap-week-charging.png
    :align: center
    
Charging (blue) mostly happens in sunshine hours, discharging during high-price hours (morning & evening)

So on a technical level, the daily heatmap is essentially a heatmap of the sensor's values, with dates on the y-axis and time of day on the x-axis. For individual devices, it gives an insight into the device's running times. A new button lets users switch between charts.

.. _view_sensors_forecast_button:

Creating a forecast
-------------------

Users with permission to record data on a sensor can create a forecast directly from the sensor page by clicking the **Create forecast** button in the left side panel. The forecast duration defaults to 48 hours (configured via ``FLEXMEASURES_PLANNING_HORIZON``) but can be adjusted up to 7 days in the panel. The button is enabled once the sensor has at least two days of historical data. After clicking, a background job is queued and the page shows progress updates via status messages. When the job finishes, the chart is refreshed to display the new forecast alongside the historical data.

See :ref:`forecasting` for more details on how FlexMeasures generates forecasts.

Annotating sensor data
----------------------

Users with permission to record data on a sensor can add a label from the **Annotate** panel on its page. Enter a label and click **Annotate**. FlexMeasures records the annotation with the signed-in user as its data source and shows it on the time chart.

The **From** and **Until** fields show the time range the label will cover. They follow the range visible in the chart, until you choose one yourself:

- Pick the select tool (the double arrow above the chart), then drag across the events you want to annotate. You can drag or resize the selection afterwards. Hold Ctrl to pan while the select tool is active.
- Or, with the select tool, click at a single moment to annotate an instant, shown as a blue rule. An instantaneous annotation has the same **From** and **Until** time.
- Or type the times into the **From** and **Until** fields.

A click outside the chart's plot area clears the selection, as it releases any pinned annotations.

A range selected on the chart, or followed from the visible chart, is widened to whole events, so the label covers every event it touches. An instant, and any selection on a sensor that records instantaneous values, is rounded to the nearest minute instead, so a selection within a minute can become an instant. Zoomed in to 10 minutes or less, these are rounded to the nearest second. Times you type are used as they are.

Histogram and heatmap charts have no time axis to select on, so there the fields follow the date range selected on the left.

Drafting sensor values
----------------------

Users with permission to record data on a sensor can sketch values on its chart from the **Draft values** panel, before anything is saved. Nothing is written to the database until you confirm a preview of them (see :ref:`saving_draft_values`).

The quickest way is to draw them. Click **Draw on chart**, then press and drag across the chart: each event your line crosses gets a draft value, at the height of your line there (rounded to what the chart can tell apart). Draw again over a part to change it. To draw above the data the chart shows, set **Highest value you want to draw**, and the chart makes room up to it; it proposes twice the top of the chart. Drawing turns on the fast chart (switching to the bar chart if a histogram or heatmap was shown), and keeps the chart from panning or zooming while it is on; **Stop drawing**, or picking another chart tool, ends it.

Or type them. Choose the time range to fill:

- Enter a **Start** and a **Duration** under **Time range**. The duration is an ISO 8601 duration, read as the sensor data API reads it: ``PT15M``, ``PT2H``, or ``P1D``, which is always 24 hours, also on a day with a daylight saving time transition.
- Or click **Select on chart**, then drag across the chart, or click once to choose a single event. This turns on the fast chart and its select tool (switching to the bar chart if a histogram or heatmap was shown); **Stop selecting** turns it off again.

Either way, the range is widened to whole events of the sensor, and a range chosen on the chart fills in **Start** and **Duration**. Type a value in the sensor's unit and click **Add** (or press Enter), and every event in the range gets that value. **Add** turns green as soon as a value is typed, and stays green once values were added. Adding over an existing draft value replaces it.

Draft values show on the chart as a dashed line, with their own legend entry, and are listed in the panel, one row per run of the same value (e.g. "40 kWh · 8 values"), where each run can be removed. **Discard** throws them away, after asking. Since draft values only live in the page, leaving or reloading it asks for confirmation first.

Draft values are not offered on touch devices, nor on sensors that record instantaneous values.

.. _saving_draft_values:

Repeating and saving draft values
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

After **Stop**, the panel shows what will be saved before anything is, and stays open while you look at the chart.

Under **Repeat**, choose to save the draft values as they are, or to repeat them **Daily** or **On the same weekday**, until a date. That date is at most one year after the draft values start, and one week after by default. Repeats keep the local time in the sensor's timezone: a value at 07:00 is repeated at 07:00, also after a daylight saving time transition. Draft values repeated daily may span at most one day, and those repeated on the same weekday at most one week.

Click **Preview**. The chart zooms out to everything that will be saved, drawn as a solid line. **Show drafts** zooms back in to the draft values, and **Show all** out again. The panel counts:

- the values to create, the draft values included;
- the values omitted because the clock skips their local time (spring forward), and those written twice because their local time occurs twice (fall back), each with a warning such as "On 28 Mar 2027 the clock skips 02:00–03:00: 4 values will not be written.". These warnings do not keep you from saving;
- the existing values that the new ones supersede, which are circled on the chart. Existing values are not deleted: they stay in the sensor's history, while the chart, and schedules that read the sensor, use the newest value for each time.

Changing the repetition or the date asks for a new preview. **Back to edit** returns to the draft values as they were, and **Discard** throws them away, after asking.

**Confirm** saves exactly what the preview showed, as the sensor data API's ``POST /sensors/<id>/data`` would, with the time of saving as their belief time, and you as their data source. Large saves may take a moment to appear on the chart.

A sensor of saved limits can then be used in a flex-model, by referring to the sensor rather than giving values (see :ref:`variable_quantities`). For instance, to use drafted state-of-charge minima in a storage schedule:

.. code-block:: json

    {
        "soc-minima": {"sensor": 42}
    }

where 42 is the ID of the sensor the values were saved on, in a unit of stored energy such as kWh.

Deleting annotations
--------------------

Users who may delete a sensor can delete its annotations from the **Delete data** panel, by choosing **Annotations** under **What**. Annotations lying entirely between the **From** and **Until** times are deleted; leave both empty to delete all of the sensor's annotations. Annotations of the sensor's asset are not affected, and an annotation that is also registered elsewhere, such as on another sensor, is only removed from this sensor.
