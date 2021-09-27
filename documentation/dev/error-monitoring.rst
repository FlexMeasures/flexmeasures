.. _dev_error_monitoring:

Error monitoring
=================

When you run a FlexMeasures server, you want to stay on top of things going wrong. We added two ways of doing that:

- You can connect to Sentry, so that all errors will be sent to your Sentry account. Add the token you got from Sentry in the config setting :ref:`sentry_access_token` and you're up and running! 
- Another source of crucial errors are things that did not even happen! For instance, a task to import prices from a day-ahead market, which you depend on later for scheduling. We added a new CLI task called ``flexmeasures monitor tasks``, so you can be alerted when tasks have not successfully run at least so-and-so many minutes ago. The alerts will also come in via Sentry, but you can also send them to email addresses with the config setting :ref:`monitoring_mail_recipients`.

For illustration of the latter monitoring, here is one example of how we monitor tasks on a server ― the below is run in a cron script every hour and checks if every listed task ran 60, 6 or 1440 minutes ago, respectively:

.. code-block:: bash

    flexmeasures monitor tasks --task get_weather_forecasts 60 --task get_recent_meter_data 6  --task import_epex_prices 1440

The first task (get_weather_forecasts) is actually supported within FlexMeasures, while the other two sit in plugins we wrote.

This task status monitoring is enabled by decorating the functions behind these tasks with:

.. code-block:: python

    @task_with_status_report
    def my_function():
        ...

Then, FlexMeasures will log if this task ran, and if it succeeded or failed. The result is in the table ``latest_task_runs``, and that's where the ``flexmeasures monitor tasks`` will look.

.. note:: The decorator should be placed right before the function (after all other decorators).

Per default the function name is used as task name. If the number of tasks accumulate (e.g. by using multiple plugins that each define a task or two), it is useful to come up with more dedicated names. You can add a custom name as argument to the decorator:

.. code-block:: python

    @task_with_status_report("pluginA_myFunction")
    def my_function():
        ...

