.. _host_error_monitoring:

Error monitoring
=================

When you run a FlexMeasures server, you want to stay on top of things going wrong. We added two ways of doing that:

- You can connect to Sentry, so that all errors will be sent to your Sentry account. Add the token you got from Sentry in the config setting :ref:`sentry_access_token` and you're up and running! 
- Another source of crucial errors are things that did not even happen! For instance, a (bot) user who is supposed to send data regularly, fails to connect with FlexMeasures. Or, a task to import prices from a day-ahead market, which you depend on later for scheduling, fails silently.


Let's look at how to monitor for things not happening in more detail:


Monitoring the time users were last seen
-----------------------------------------

The CLI task ``flexmeasures monitor last-seen`` lets you be alerted if a user has contacted your FlexMeasures instance longer ago than you expect. This is most useful for bot users (a.k.a. scripts).

Here is an example for illustration:

.. code-block:: bash

    $ flexmeasures monitor last-seen --account-role SubscriberToServiceXYZ --user-role bot --maximum-minutes-since-last-seen 100

As you see, users are filtered by roles. You might need to add roles before this works as you want.

.. todo:: Adding roles and assigning them to users and/or accounts is not supported by the CLI or UI yet (besides ``flexmeasures add account-role``). This is `work in progress <https://github.com/FlexMeasures/flexmeasures/projects/18>`_. Right now, it requires you to add roles on the database level. 


Monitoring task runs
---------------------

The CLI task ``flexmeasures monitor latest-run`` lets you be alerted when tasks have not successfully run at least so-and-so many minutes ago.
The alerts will come in via Sentry, but you can also send them to email addresses with the config setting :ref:`monitoring_mail_recipients`.

For illustration, here is one example of how we monitor the latest run times of tasks on a server ― the below is run in a cron script every hour and checks if every listed task ran 60, 6 or 1440 minutes ago, respectively:

.. code-block:: bash

    $ flexmeasures monitor latest-run --task get_weather_forecasts 60 --task get_recent_meter_data 6  --task import_epex_prices 1440

The first task (get_weather_forecasts) is actually supported within FlexMeasures, while the other two sit in plugins we wrote.

This task status monitoring is enabled by decorating the functions behind these tasks with:

.. code-block:: python

    @task_with_status_report
    def my_function():
        ...

Then, FlexMeasures will log if this task ran, and if it succeeded or failed. The result is in the table ``latest_task_runs``, and that's where the ``flexmeasures monitor latest-run`` will look.

.. note:: The decorator should be placed right before the function (after all other decorators).

Per default the function name is used as task name. If the number of tasks accumulate (e.g. by using multiple plugins that each define a task or two), it is useful to come up with more dedicated names. You can add a custom name as argument to the decorator:

.. code-block:: python

    @task_with_status_report("pluginA_myFunction")
    def my_function():
        ...

