.. _docker-image:

Running via Docker
======================

FlexMeasures can be run via `its docker image <https://hub.docker.com/repository/docker/lfenergy/flexmeasures>`_.

`Docker <https://docs.docker.com/get-docker/>`_ is great to save developers from installation trouble, but also for running FlexMeasures inside modern cloud environments in a scalable manner.


.. note:: We also support running all needed parts of a FlexMeasures web service setup via `docker-compose <https://docs.docker.com/compose/>`_, which is helpful for developers and might inform hosting efforts. See :ref:`docker-compose`. 


Getting the `flexmeasures` image
-----------------------------------

You can use versions we host at Docker Hub, e.g.:

.. code-block:: bash

    $ docker pull lfenergy/flexmeasures:latest


You can also build the FlexMeasures image yourself, from source:

.. code-block:: bash

    $ docker build -t flexmeasures/my-version . 

The tag is your choice.


Running
-----------------------------------

Running the image (as a container) might work like this (remember to get the image first, see above):

.. code-block:: bash

    $ docker run --env SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname --env SECRET_KEY=blabla --env FLEXMEASURES_ENV=development -p 5000:5000 -d --net=host lfenergy/flexmeasures

.. note:: Don't know what your image is called (its "tag")? We used ``lfenergy/flexmeasures`` here, as that should be the name when pulling it from Docker Hub. You can run ``docker images`` to see which images you have.

.. include:: ../notes/macOS-docker-port-note.rst

The two minimal environment variables to run the container successfully are ``SQLALCHEMY_DATABASE_URI`` and the ``SECRET_KEY``, see :ref:`configuration`. ``FLEXMEASURES_ENV=development`` is needed if you do not have an SSL certificate set up (the default mode is ``production``, and in that mode FlexMeasures requires https for security reasons). If you see too much output, you can also set ``LOGGING_LEVEL=INFO``.

In this example, we connect to a postgres database running on our local computer, so we use the host network. In the docker-compose section below, we use a Docker container for the database, as well.

Browsing ``http://localhost:5000`` should work now and ask you to log in.
Of course, you might not have created a user. You can use ``docker exec -it <flexmeasures-container-name> bash`` to go inside the container and use the :ref:`cli` to create everything you need.


.. _docker_configuration:

Configuration and customization
-----------------------------------

Using :ref:`configuration` by file is usually what you want to do. It's easier than adding environment variables to ``docker run``. Also, not all settings can be given via environment variables. A good example is the :ref:`mapbox_access_token`, so you can load maps on the dashboard.

To load a configuration file into the container when starting up, we make use of the `instance folder <https://flask.palletsprojects.com/en/2.1.x/config/#instance-folders>`_. You can put a configuration file called ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance`` and then mount that folder into the container, like this:

.. code-block:: bash

    $ docker run -v $(pwd)/flexmeasures-instance:/app/instance:ro -d --net=host lfenergy/flexmeasures

.. warning:: The location of the instance folder depends on how we serve FlexMeasures. The above works with gunicorn. See the compose file for an alternative (for the FlexMeasures CLI), and you can also read the above link about the instance folder.

Installing plugins within the container
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

At this point, the FlexMeasures container is up and running without including any plugins you might need to use. To integrate a plugin into the container, follow these steps:

1. Copy the plugin into your active FlexMeasures container by executing the following command:

.. code-block:: bash

    docker cp </path/to/plugin-directory> <flexmeasures-container-name>:/app


2. Once the plugin is successfully copied proceed to install it, for instance using pip ``docker exec -it <flexmeasures-container-name> bash -c "pip install <path/to-package>"``. Instead, you just need to install the requirements, then run this command ``docker exec -it <flexmeasures-container-name> bash -c "pip install -r <path/to-package/requirements.txt``.
3. After completing the installation, create a directory named ``instance`` in the container working directory and transfer the FlexMeasures configuration file, ``flexmeasures.cfg``, into it using the ``docker cp`` command. Additionally, ensure that you incorporate your plugin details into the ``flexmeasures.cfg`` file as outlined in the :ref:`plugin-config` section.
4. Once these steps are finished, halt the container using the ``docker stop <flexmeasures-container-name>`` command, followed by restarting it using ``docker start <flexmeasures-container-name>``. This ensures that the changes take effect. Now, you can make use of the installed plugins within the FlexMeasures Docker container.